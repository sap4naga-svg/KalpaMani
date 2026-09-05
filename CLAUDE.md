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
**PHASE 3A — BOUNDED AUTHENTICATED ACQUISITION QUALIFICATION: IMPLEMENTED — PR #35 MERGED — ATTEMPTED TWICE UNDER SEPARATE AUTHORIZATIONS. ATTEMPT ONE REFUSED AT THE AWS IDENTITY GATE (`REFUSED_IDENTITY`, EXIT CODE 6), WITH NO PROVIDER REQUEST, NO CREDENTIAL RETRIEVAL AND NO PUBLICATION. ATTEMPT TWO COMPLETED (`COMPLETED`, EXIT CODE 0), REACHED THE QUALIFICATION RUNTIME AND MADE ONE PROVIDER REQUEST; ITS S3 QUALIFICATION OPERATIONS ARE BOUNDED AT THREE TO SIX — EXACTLY THREE PUTOBJECT AND ZERO TO THREE CONDITIONAL HEADOBJECT — WITH A COMPLETE RETAINED ACQUISITION RECORD, AND HOW MANY OBJECTS WERE NEWLY WRITTEN NOT ESTABLISHED. COMPLETION IS A COMMAND STATUS — NOT QUALIFICATION PASSED, NOT PROVIDER ACCEPTANCE AND NOT PROVIDER SELECTION; EXACT-REQUEST AUTHENTICATION ESTABLISHED, PROVIDER-WIDE AUTHENTICATION UNKNOWN. A THIRD ATTEMPT NOT AUTHORIZED.**
**PHASE 3A — BOUNDED PRIVATE EMPIRICAL QUALIFICATION: RUN A COMPLETED ONCE (2026-09-04) — ONE ENTRY-POINT INVOCATION, EXIT CODE 0, 48 PROVIDER REQUESTS, ZERO PROVIDER RETRIES, 145 APPEND-ONLY LICENSED-S3 WRITES, ZERO OBJECT-BYTE READS, ZERO LISTINGS, ZERO CONTROL OPERATIONS, ONE CREDENTIAL RETRIEVAL, ZERO TERRAFORM OPERATIONS, LOCATOR PUBLISHED LAST AND ADDRESSABLE, EXECUTION IDENTIFIER PERMANENTLY RETIRED. A COMMAND OUTCOME, NOT A PROVIDER VERDICT: P1–P9 UNEVALUATED, A RUN A RETRY NOT AUTHORIZED, RUN B NOT AUTHORIZED AND AT LEAST EIGHT CALENDAR DAYS LATER WITH AN EARLIEST APPROVED TARGET OF 2026-09-12, COMBINED ASSESSMENT NOT AUTHORIZED, NO PROVIDER SELECTED.**
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

Breakout / Pullback / PEAD / Deterioration Short strategy logic; the Strategy Brain runtime;
short-selling logic; AI Research or Challenger agents; the portfolio/risk engine; the scanner and factor pipeline; **any point-in-time data
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

**The Strategy Brain is SPECIFIED and NOT IMPLEMENTED.** A reviewable specification exists at
[`docs/phase4/strategy-brain-specification.md`](docs/phase4/strategy-brain-specification.md) under
**[ADR-0026](docs/decisions/ADR-0026-strategy-brain-architecture-and-governance.md) — ACCEPTED EFFECTIVE ON
MERGE OF PR #70, and PROPOSED and carrying no authority until that merge**. **A specification is not an
implementation**: no Brain runtime module, strategy module, factor calculation, scanner, AI agent,
portfolio sizing or order routing exists, and **none is authorized**. **Specification,
implementation, research, deployment and execution are five separate gates** — see *The Strategy
Brain specification* below.

**The Cockpit is SPECIFIED and NOT IMPLEMENTED.** A reviewable specification package exists at
[`docs/architecture/COCKPIT_FEEDBACK_EXTENSION.md`](docs/architecture/COCKPIT_FEEDBACK_EXTENSION.md)
and [`docs/cockpit/`](docs/cockpit/cockpit-v1-specification.md) under
**[ADR-0027](docs/decisions/ADR-0027-cockpit-and-feedback-architecture-and-governance.md) — ACCEPTED EFFECTIVE ON
MERGE OF PR #71, and PROPOSED and carrying no authority until that merge**. **A specification is not
an implementation**: no Cockpit application, read API, projection runtime, metric engine, feedback
automation, database, migration or scheduler exists, and **none is authorized**. **V1 is
observational**, and **every future control is inert with no handler and no control API route** — see
*The Cockpit and Feedback specification* below.

### Current phase state

**PHASE 3 — POINT-IN-TIME DATA FOUNDATION.**

| | |
|---|---|
| **PHASE 3 PLANNING** | **ACCEPTED / MERGED** |
| **PHASE 3A — A1 FOUNDATION KERNEL** | **ACCEPTED (2026-08-27)** |
| **PHASE 3A — SHARADAR PROVIDER-INTEGRATION SLICE 1** | **IMPLEMENTED / ACCEPTED (ADR-0009, PR #13 merged) — CODE ONLY** |
| **PHASE 3A — LICENSED S3 RESEARCH OBJECT STORE** | **IMPLEMENTED / ACCEPTED — PR #16 MERGED — CODE ONLY, NEVER RUN AGAINST AWS** |
| **PHASE 3A — SHARADAR QUALIFICATION RUNTIME CORE** | **IMPLEMENTED / ACCEPTED — PR #17 MERGED — CODE ONLY, NEVER RUN AGAINST SHARADAR OR AWS** |
| **PHASE 3 OVERALL** | **NOT COMPLETE** |
| **Full Stage 3A real-data ingestion** | **NOT AUTHORIZED** |
| **PHASE 3A — A2 / A3 subscription / purchase** | **AUTHORIZED AND PURCHASED (2026-08-28, ADR-0010)** — one month, Full History Bundle, Personal Use, **for qualification only** |
| **Owner-side credential setup · application credential retrieval · provider API access · Services Data ingestion** | Owner-side Sharadar secret creation and identifier configuration **OWNER-CONFIGURED, AND RESOLVED ONCE BY THE ENTRY POINT** on the fifth authorized binding-preflight attempt, which retrieved **one** credential and had it **structurally accepted**. **Additional** application credential retrieval **NOT AUTHORIZED**, provider API access **NOT AUTHORIZED**, Services Data access and ingestion **NOT AUTHORIZED**, a **third** authenticated qualification attempt **NOT AUTHORIZED** — two attempts occurred, the first refusing at the AWS identity gate before reaching any credential and the second completing without establishing that any credential authenticated; a subscription existing is not permission to use it, a configured secret is not permission to read it again, and a structurally accepted credential is not proof that it authenticates against Sharadar, which stays **UNKNOWN** |
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
| **[ADR-0013](docs/decisions/ADR-0013-introduce-acquisition-mode-and-retire-is-backfill.md) — acquisition mode, `is_backfill` retired** | **ACCEPTED / IN FORCE** — PR #18 merged |
| **G1** provider selection · **G2** production information-set profile | **OPEN** |
| **G3** vendor licensing — Sharadar personal use | **CLOSED (2026-08-27, ADR-0008)** |
| **G4** analyst revisions · **G5** historical borrow | **OPEN** |
| **G6 options overlay · G7 strategy-taxonomy evidence** | **OPEN (added by V3.0)** |
| **AWS account** | **EXISTING** — pre-dates this work; configured for the KalpaMani foundation 2026-08-27 |
| **AWS research foundation** | **PROVISIONED (2026-08-27)** — 36 resources, verified 66/66 |
| **Cloud spend beyond the idle foundation** | **NOT AUTHORIZED** |
| **Any further AWS mutation, read, verifier run or Terraform command** | **NOT AUTHORIZED** — implementing a client-shaped adapter is not permission to run one. Five separately authorized binding-preflight attempts, two SSO logins and two identity diagnostics have occurred and are recorded; each was authorized for itself, and none of them authorizes the next |
| **Licensed bucket · SDK client construction · credential source** | Licensed-bucket resolutions **ONE**, S3 client constructions **ONE**, S3 object operations **ZERO** — the phrase *real bucket binding* is **undefined in this repository**, so the status is those three facts and neither a claimed binding nor a claimed absence. Operational secret-identifier configuration **OWNER-CONFIGURED, AND RESOLVED ONCE BY THE ENTRY POINT**, Secrets Manager client constructions **ONE**. A provider-neutral credential-source boundary **exists**, and the **ADR-0015 operator entry point is the sole permitted construction boundary** — invoked five times under separate authorization, the first four refusing without constructing a client and the fifth **COMPLETING** with **one** Secrets Manager client, **one** admitted `get_secret_value`, **one** retrieved and structurally accepted credential, **one** S3 client, **one** provider transport and **one** offline composition preflight returning **`VALIDATED_OFFLINE`**. A corrected AWS SSO login **COMPLETED SUCCESSFULLY** beforehand and **one** sanitized identity confirmation returned **`IDENTITY_CONFIRMED`**, which bound nothing and verified no secret, credential, bucket or provider access. A sixth binding-preflight attempt **NOT AUTHORIZED**, further AWS authentication diagnosis **NOT AUTHORIZED**, another AWS SSO-login/refresh attempt **SEPARATELY GATED / NOT AUTHORIZED**, additional credential or Secrets Manager access **NOT AUTHORIZED**; SDK or client construction outside that boundary **NOT AUTHORIZED** |
| **[ADR-0014](docs/decisions/ADR-0014-implement-the-dormant-sharadar-qualification-composition-root.md) — dormant composition root + offline preflight** | **ACCEPTED / IN FORCE** — PR #19 merged. One dormant composition root exists and **offline preflight exists**; **qualification-run execution surface NONE**, **provider-fetch operation NONE**, **object-publication operation NONE**, **runner NONE**, provider and AWS requests **ZERO** |
| **[ADR-0015](docs/decisions/ADR-0015-implement-the-dormant-sharadar-private-binding-preflight.md) — dormant private-binding preflight** | **ACCEPTED / IN FORCE** — PR #22 merged. One operator entry point exists and is **refused by default**; **binding preflight only**. **Four separately authorized attempts occurred and all four refused, and a fifth separately authorized attempt then COMPLETED** — the four refusing at the identity gate, on a missing local AWS SDK, at the fixed secret-identifier source with **`REFUSED_SECRET_IDENTIFIER`**, and at the identity gate again with **`REFUSED_IDENTITY`** — so **AWS identity-gate activity occurred** and total AWS activity was not zero, while **AWS network requests on the fourth attempt are UNKNOWN** and no **standalone** diagnosis was performed as part of the attempt — while its governed identity gate's own **STS command invocation is UNKNOWN**, because the committed gate has real pre-STS refusal paths and nothing tracked records which branch refused. A **separately authorized post-fourth standalone AWS identity diagnosis has since COMPLETED** with **`REFUSED_SSO_SESSION_MISSING_OR_EXPIRED`** — one process, one `aws sts get-caller-identity` command, exit code **255**, **missing and expired not distinguished**, the governed profile pinned in the child environment and never disclosed, its **own** underlying AWS network-request count **UNKNOWN**, and at that point **SSO-login invocations were ZERO**, **authentication-repair actions were ZERO** and **fifth binding-preflight attempts were ZERO**. A **separately authorized post-diagnosis AWS SSO-login attempt has since COMPLETED** with **`REFUSED_SSO_LOGIN`** — **one** `aws sso login --no-cli-pager` command invocation, **timed out after 420 seconds**, terminated with **no lingering AWS CLI process** and therefore **exit code NOT AVAILABLE / PROCESS TERMINATED ON TIMEOUT**, **browser authorization interactions ZERO**, **device authorizations completed ZERO**, **successful SSO refreshes ZERO**, **identity-confirmation command invocations ZERO**, **fifth binding-preflight attempts ZERO**, its own underlying AWS network-request count **UNKNOWN**, the SSO session **still unrefreshed after it**, the earlier **`REFUSED_SSO_SESSION_MISSING_OR_EXPIRED`** diagnosis **unrevised**, and the likely cause recorded as **suppression of the interactive browser/device-code surface — likely, not proven**. A **corrected second AWS SSO-login attempt has since COMPLETED SUCCESSFULLY** — one `aws sso login --no-cli-pager` command in a new Claude session on a **live console with inherited stdin, stdout and stderr**, **no captured, piped, redirected, buffered or file output**, the **interactive browser/device flow completed**, **exit code `0`**, **no lingering AWS CLI process**, **successful governed SSO refreshes ONE**, a **minimal allowlisted child environment built key-by-key** with **no whole-environment copy** and **no credential-bearing ambient variable copied or inspected**, the governed profile from a **static AST parse of `EXPECTED_PROFILE`** and never disclosed, the **verification URL and one-time device code transient in the live console only**, and its own underlying AWS network-request count **UNKNOWN**. Because that login exited `0`, **exactly one sanitized identity confirmation ran** — `aws sts get-caller-identity --no-cli-pager --output json`, **exit code `0`**, **non-empty `UserId`, `Account` and `Arn` structurally present**, **raw response and private identity values neither displayed nor persisted**, classified **`IDENTITY_CONFIRMED`**, **captured buffers cleared after classification**, its own network-request count **UNKNOWN**, **identity confirmed at the time of that command with no guarantee of current or future session validity**, and **verifying no secret identifier, secret, credential, bucket or provider access**. **The fifth separately authorized attempt then ran exactly once and COMPLETED** — **exit code `0`**, public output exactly `binding preflight completed` and `offline validation completed`, closed outcome **`COMPLETED + VALIDATION_COMPLETED`**, and a last definitively reached stage of **stage 10**: one `preflight_qualification_composition` invocation returning **`VALIDATED_OFFLINE`**. Its conservative counts are identity-gate invocations **ONE, passed**, licensed-bucket resolutions **ONE**, secret-identifier resolutions **ONE**, Secrets Manager client constructions **ONE**, `get_secret_value` invocations **ONE, admitted**, S3 client constructions **ONE**, S3 object operations **ZERO**, provider transport constructions **ONE**, Sharadar/provider requests **ZERO**, offline composition-preflight invocations **ONE**, qualification executions **ZERO**, and underlying AWS network requests **UNKNOWN**. **A credential was definitively retrieved**: one admitted `get_secret_value` returned a `SecretString` the existing credential contract accepted **structurally**, which was passed into the offline composition and **never displayed, logged, persisted, hashed, fingerprinted, measured or summarized** — *usable* meaning structurally acceptable to that contract, with **Sharadar authentication UNKNOWN** because **no provider request occurred**. The fourth attempt still **reached neither licensed-bucket resolution nor the secret-identifier source** and **did not read `KALPAMANI_SHARADAR_SECRET_ID`**; operational secret-identifier configuration is **OWNER-CONFIGURED, AND RESOLVED ONCE BY THE ENTRY POINT** on the fifth attempt, owner setup having occurred **after the third attempt** and **before the fourth**. A **sixth** attempt, **further AWS authentication diagnosis**, **another AWS SSO refresh or login — separately gated**, **additional credential or Secrets Manager access**, **Sharadar/provider access**, **any S3 object operation or publication**, **ingestion, backfill and update** and a **third authenticated qualification attempt stay separately gated and NOT AUTHORIZED** |
| **[ADR-0016](docs/decisions/ADR-0016-correct-private-binding-preflight-failure-boundaries.md) — corrected private-binding failure boundaries** | **ACCEPTED / IN FORCE** — PR #24 merged. Separates **secret-identifier**, **local dependency**, **unclassified** and **credential** refusals. The corrected boundaries were exercised for the first time by the fifth attempt, which passed the identifier stage rather than refusing at it: Secrets Manager client constructions **ONE**, `get_secret_value` invocations **ONE, admitted**, Secrets Manager underlying network requests **UNKNOWN**, real credential retrieval **ONE, structurally accepted**. Operational environment **SYNCHRONIZED AND VERIFIED**, Python dependency lock **ABSENT**, environment **RANGE-CONFORMANT NOT LOCK-CONFORMANT**, further environment resynchronization **SEPARATELY GATED**, a sixth binding-preflight attempt **NOT AUTHORIZED**, additional credential or Secrets Manager access **NOT AUTHORIZED**, a **third** authenticated qualification attempt **NOT AUTHORIZED** — of the two attempts that occurred, the first refused at the AWS identity gate, two stages before this boundary, and the second completed, so these corrected refusals were exercised by neither |
| **[ADR-0017](docs/decisions/ADR-0017-bounded-authenticated-sharadar-acquisition-qualification.md) — bounded authenticated acquisition qualification** | **ACCEPTED / IN FORCE** — PR #33 merged. Merge commit **`4fab37cd9468bc48b62a80e49e5a17a203870926`**, approved ADR head **`679863fd7f540f47ae4f47aee8d5e363d72caffd`**. **The merge acceptance condition has occurred**, so ADR-0017 is **no longer PROPOSED** — while its pull request was open it was **not accepted and carried no authority**, which was true then and is not rewritten. **The authenticated acquisition entry point is now IMPLEMENTED, ATTEMPTED TWICE — REFUSED, THEN COMPLETED.** `scripts/sharadar_authenticated_qualification.py` exists, **refuses by default**, and the accepted composition root was **extended, not duplicated**: `QualificationRuntime.execute` now has **exactly ONE ADR-0017 production caller**, reached only through that entry point's authorized branch, and the repository now has **exactly TWO production call sites overall** — that unchanged ADR-0017 composition, and the separate dormant ADR-0018 / ADR-0019 / ADR-0020 qualification acquisition path merged by PR #48. **The second caller does not alter, broaden or become reachable from ADR-0017**, and **assessment read composition remains separate from acquisition**. **Before that dormant implementation merged the ADR-0017 caller was the only one** — true then, and not rewritten. **Authenticated entry points implemented ONE.** **Implementing it was not permission to use it, one refused attempt is not permission for a second, and one completed attempt is not permission for a third**: **a third execution of the surface remains separately gated and NOT AUTHORIZED**, and **implementation, execution and empirical qualification remain three distinct gates**. **Two separately authorized executions have since been attempted, in fresh sessions: the first REFUSED and the second COMPLETED.** Authenticated qualification attempts **TWO — one refused, one completed**, entry-point process invocations **TWO — exactly one per attempt**. **Attempt one:** closed outcome **`REFUSED_IDENTITY`**, exit code **`6`**, last stage definitively reached **stage 5 — the AWS identity gate**, stages 1–4 **PASSED**; AWS identity-gate invocations **ONE, refused**, licensed-bucket resolutions **ZERO**, Terraform command invocations **ZERO**, secret-identifier resolutions **ZERO**, `KALPAMANI_SHARADAR_SECRET_ID` reads **ZERO**, Secrets Manager client constructions **ZERO**, `get_secret_value` invocations **ZERO**, credential retrievals by this attempt **ZERO**, S3 client constructions **ZERO**, provider transport constructions **ZERO**, qualification-runtime executions against real services **ZERO**, application-level provider fetches **ZERO**, Sharadar/provider requests **ZERO**, `PutObject` **ZERO**, conditional `HeadObject` **ZERO**, S3 object-byte reads **ZERO**, S3 qualification operations **ZERO**, CONTROL operations **ZERO**, `.runtime/` writes from this attempt **ZERO**, and underlying AWS/network interactions **UNKNOWN**; the gate's own STS command invocation is **UNKNOWN** because real pre-STS refusal paths exist, and the **cause of the refusal was not diagnosed and is not inferred**. **Attempt two:** entry-point process invocations **ONE**, exit code **`0`**, closed result observed **YES**, closed result **`COMPLETED`**, qualification runtime reached **YES**, qualification-runtime executions **ONE**, provider requests **ONE**, `PutObject` invocations **EXACTLY THREE**, conditional `HeadObject` invocations **ZERO TO THREE**, S3 qualification operations **THREE TO SIX**, publication state unknown **NO**, complete acquisition record **EXISTS**, newly written objects **NOT ESTABLISHED**, already-present identical objects **NOT ESTABLISHED**, and underlying AWS/network interactions **UNKNOWN** — the bounds derived from the closed token's committed meaning, not from any S3 or provider inspection. **`COMPLETED` is a command status, not a verdict** — not qualification passed, not the provider accepted, not a provider selected, not a closure of G1 or G2, not a completion of Phase 3, and not production, CONTROL or live-trading readiness. Cumulatively: qualification-runtime executions **ONE**, known provider requests **ONE**, S3 qualification operations **THREE TO SIX — attempt one ZERO, attempt two THREE TO SIX**, exact-request authentication **ESTABLISHED**, provider-wide authentication **UNKNOWN**, subscription-wide entitlement **UNKNOWN**, P1–P9 executions **ZERO**, ingestion and trading operations **ZERO**. Credential retrievals established by count remain **ONE**, from the fifth binding-preflight attempt, with attempt two's count **NOT ESTABLISHED** by count, and binding-preflight attempts remain **FIVE** — neither attempt was a sixth. **A third authenticated attempt, further AWS identity diagnosis and another SSO refresh or login are each NOT AUTHORIZED.** The implemented path preserves **one request = one durable acquisition**, keeps the acquisition runtime's **opaque-payload boundary** with **no parser introduced**, declares **`AcquisitionMode.QUALIFICATION`** with **no fourth mode**, locks **one provider request** with **no pagination** and **no automatic retry** over a **seven-day trailing window**, and publishes byte for byte through the **licensed private Bronze data plane** only as **three durable artifacts** in **exactly three PutObject operations** with **zero-to-three conditional HeadObject metadata checks only after 412**, **zero object-byte reads**, **zero `.runtime/` writes** and **no extra qualification report**, performing **no CONTROL publication**. Full **P1–P9 empirical qualification remains separate and unexecuted**, **no provider is selected**, and **G1 and G2 stay OPEN** |
| **[ADR-0018](docs/decisions/ADR-0018-bounded-private-empirical-sharadar-qualification.md) — bounded private empirical Sharadar qualification** | **ACCEPTED / IN FORCE** — PR #39 merged. Merge commit **`97e7ce57bb90303c78c2a1a4bc3ac2301b60f694`**, approved ADR head **`25ee0b0a6ab17c1fea7e2fa4ccd72ce8b2864780`**. **The conditional acceptance event has occurred**, so **ADR-0018: ACCEPTED / IN FORCE**. **While PR #39 was open it was proposed and carried no authority** — that is a historical fact about those days, it stays true, and it is **not** rewritten as though the document had authority before its merge. **The merge approved ARCHITECTURE ONLY** — the evidence inventory, the P1–P9 ceilings, the two-process split, the deterministic private locator, the operation arithmetic, the two least-privilege roles, the parser/evaluator/report boundaries and the deletion-runbook clarification. **The merge authorized NO implementation, NO infrastructure mutation and NO execution**: implementation under `src/`, a new entry point, an IAM role, a Terraform plan or apply, a binding preflight, Run A, Run B, an assessment run, a provider request, an S3 operation, a credential retrieval, a private report, a P1–P9 execution, a provider selection and a G1 or G2 decision each stayed **separately gated** on that day. **The implementation gate has since been crossed under a later, separate authorization and PR #41 merged**, and the rest are unchanged — **ADR-0018 implementation execution: NOT AUTHORIZED · infrastructure mutation: NOT AUTHORIZED · Run A: NOT AUTHORIZED · Run B: NOT AUTHORIZED · assessment: NOT AUTHORIZED**. **It supersedes nothing** and rewrites neither ADR-0011 nor ADR-0017: ADR-0011's *no read surface* stays true of the store it authorized, and **ADR-0017's exactly-three-`PutObject` accounting is untouched** — the designed surface is a **different** surface with its own accounting and may never be reached through the ADR-0017 entry point. Designed inventory: **eight private subject classes, recorded as classes and never as names**; datasets **`tickers`, `stocks`, `actions`** only; `tickers` **snapshot, no window**; `stocks` and `actions` **1998-01-01 → `T−1`**; page limits **100 / 10,000 / 10,000**; **two pages maximum**, the second a **completeness probe and not an invitation to paginate**; **48 requests per run**; **`max_attempts = 1`, zero provider retries — arithmetically forced**, because 48 requests against the compiled retry budget of 32 leave no room for one; **4 MiB per response**, **64 MiB per run**, **30-second timeout**, **≥1-second pacing**, **sequential only**, a **1,800-second acquisition elapsed-time deadline** measured on an **injected monotonic clock** over the complete acquisition execution phase — provider requests, pacing, local processing, Bronze publication, metadata resolution, locator construction, locator publication and permitted locator retry — and **not** compile-time arithmetic; **two runs at least eight calendar days apart, each separately authorized with a distinct execution identity**, **96 provider requests maximum across both**. Ceilings: **P1** `PARTIALLY_TESTED` after Run A and **at most `TESTED`** after Run B, information time **bounded regardless**; **P2 at most `PARTIALLY_TESTED`** — sampled existence is **not** proof of the population-wide survivorship claim; **P3** schema question may reach `TESTED`, timing **approximated**; **P4 `DOCUMENTATION_RESOLVED`** — a snapshot table has no time axis to sample; **P5 realistically at most `PARTIALLY_TESTED`**, spinoff limb inconclusive while provider semantics stay undocumented; **P6, P7, P8 `DEFERRED`**; **P9 `DOCUMENTATION_RESOLVED`**, price origin **`PROVIDER_DERIVED`**, **`PUBLIC_PIT` not reachable**. **No aggregate verdict, no provider-selection value and no readiness value exists anywhere in the design.** Locator: **one per execution**, `licensed/qualification/sharadar/locators/<execution-id>.json`, **LICENSED**, **published last**, **append-only and conditional**, **closed schema with no free text**, **≤256 KiB**, binding the plan and private inventory by digest and every claim, payload and record to an exact key, expected digest, byte count and disposition, **never a cross-execution index**, **never listed**, and **a `PARTIAL`, missing, collided, ambiguous or unverified locator fails closed and is refused for evaluation**. Arithmetic, **nominal**: provider requests **48**, provider retries **ZERO**, Bronze `PutObject` **144**, locator `PutObject` **1**, total `PutObject` **145**, conditional `HeadObject` **0–145**, object-byte `GetObject` **ZERO**, listing **ZERO**, CONTROL **ZERO**, total S3 operations **145–290**. **Maximum**, with the locator's **at most two** retries — permitted **only** on `THROTTLED` or `TRANSIENT` and **never** after an ambiguous or unclassified result: locator `PutObject` **≤3**, total `PutObject` **≤147**, conditional `HeadObject` **0–145** — 144 Bronze plus **at most one** locator, because a retry-triggering attempt sends none — total S3 operations **147–292**, and **294–584** across the two acquisition runs; a complete run reports **144 ≤ `PutObject` ≤ 147** as the **real observed invocation count**, never "exactly 145" when a retry occurred. Assessment, exact — **one COMBINED assessment over BOTH executions**, after Run B: `GetObject` **`E × (2R + 1)` = 194** — **two** locators, **96** acquisition records, **96** payloads, **zero claims** — report `PutObject` **1**, conditional `HeadObject` **0–1**, total **195–196**; on a refused locator or pair **`GetObject` 0–2 and every other operation ZERO**, with **no payload read**. Whole package: **two acquisition runs 290–584**, **combined assessment 195–196**, **whole empirical package 485–780** S3 operations. **The superseded canonical arithmetic is gone** — a one-locator assessment is no longer canonical, and neither is its read total of 97, its operation total of 98-to-99, or the 196-to-198 total that assumed one assessment per run. Roles: **two, with separate sessions** — the **acquisition role cannot read object bytes**, the **assessment role can retrieve no credential and reach no provider**, and the **deletion role is unchanged, stays separate and cannot read**. **The clarification amendment is EFFECTIVE — PR #42 merged**, merge commit **`28239514b9e4e13f55ee98fa50877077e70bd593`**, approved clarification head **`579259a62ff7561ae2991f3923ea8aa1d0064be8`** — **the conditional effectiveness event has occurred**, so **ADR-0018's total elapsed acquisition deadline clarification is now effective** and **ADR-0018's combined Run A / Run B assessment clarification is now effective**. **While PR #42 was open the clarification was proposed and carried no authority** — a historical fact about those days that stays true and is not rewritten as though the clarification had always been effective. **The merge approved clarification of architecture only**, and **the clarification merge authorized no implementation, no infrastructure mutation and no execution** — implementation, infrastructure mutation, Run A, Run B and the combined assessment each stay separately gated. **The offline implementation is merged, dormant and never executed**; it was **corrected against the now-authoritative clarification** under a separately authorized implementation correction, and **the independent re-review has since occurred and produced the fixed-count correction merged as PR #44**. A **sanitized incident** is recorded: an **unauthorized directory listing beneath the private runtime area** observed **owner-side filenames but read no file contents**, the review **did not reproduce it**, **no tracked contamination was found by the read-only review**, the **filenames are intentionally not disclosed**, and it **authorizes neither private-directory inspection nor further diagnosis**. Current state: **empirical-package executions ZERO · provider requests by this package ZERO · S3 operations by this package ZERO · P1–P9 executions by this package ZERO · locators ZERO · private reports ZERO · new IAM roles ZERO · the licensed object-byte read surface is MERGED, DORMANT AND NOT DEPLOYED**. **The bounded assessment-only read implementation now exists in committed code**, **it is dormant and not deployed**, **it permits no S3 listing**, **it is not a general read surface**, **it has never been executed against licensed objects**, **no locator, record, payload or report has been read by the empirical package**, **the acquisition process remains write-only**, and **the ordinary ingestion path remains unable to use the qualification read surface**. **G1 OPEN · G2 OPEN**, no provider selected, Phase 3 **NOT COMPLETE**, CONTROL **DEFERRED**, live trading **HARD-DISABLED**, and a **third ADR-0017 attempt NOT AUTHORIZED**. **AMENDED BY ADR-0019 — PR #46 merged.** The acquisition-side figures in this row — the `zero to 145` conditional `HeadObject` range, the `145–290` and `147–292` per-run totals, the `294–584` two-run total, the `485–780` package envelope, the `6 × T_s3` per-request collision allowance and the `4 × T_s3` locator allowance — are **ADR-0018's original accepted arithmetic** and **no longer govern**. They are retained here as history and as an explanation of what ADR-0019 amended. **The governing acquisition arithmetic is now ADR-0019's**: acquisition `PutObject` **145–147**, acquisition `HeadObject` **exactly 0**, acquisition `GetObject` **exactly 0**, two successful runs **290–294**, assessment **unchanged at 195–196**, whole successful package **485–490**. ADR-0018's own document is unchanged and is not rewritten |
| **[ADR-0019](docs/decisions/ADR-0019-write-only-acquisition-collision-policy.md) — write-only acquisition, fail-closed collision policy** | **ACCEPTED / IN FORCE** — PR #46 merged. Merge commit **`77974f476ead96548beb16543dfd3db8c03232c3`**, approved ADR head **`bf0414c4a915d85a124ba400284ca1fa671fda27`**, merged **2026-09-01T01:01:22Z**. **ADR-0019's conditional acceptance event has occurred**, and **PR #46 was independently reviewed before its merge**. **While PR #46 was open ADR-0019 was proposed and carried no authority**, and **ADR-0018's original collision-resolution design and arithmetic governed before the PR #46 merge** — historical facts that stay true and are not rewritten. **The merge approved architecture only, and authorized no production-code correction**, no Terraform, no IAM, no infrastructure mutation, no deployment and no execution. **ADR-0019 supersedes no ADR wholesale**; it **narrowly amends the enumerated clauses of ADR-0018** — §4.5.3, §7.4, §9.1, §9.2, §9.3, §9.5 and §10.1. **ADR-0018 remains ACCEPTED / IN FORCE except as amended by ADR-0019**, **ADR-0017 is not amended or superseded**, **ADR-0011 is not amended or superseded**, and **the shared S3ResearchObjectStore remains unchanged**. Authoritative architecture: **the acquisition role receives no s3:GetObject**, **no s3:GetObjectVersion**, **no s3:GetObjectAttributes**, and no listing, copy, delete or CONTROL authority; **the acquisition publication surface has no head_object** and **no get_object**; **acquisition HeadObject: exactly 0**; **acquisition GetObject: exactly 0**; **every acquisition-side conditional PutObject collision fails closed**; **a 412 does not establish that the occupied object is identical**; **BRONZE_NAME_OCCUPIED** and **LOCATOR_NAME_OCCUPIED** are the authoritative closed outcomes, and **LOCATOR_NOT_PUBLISHED** remains the result when no truthful locator can be published. Governing arithmetic: **acquisition PutObject: 145 to 147**, **two successful runs: 290 to 294**, **assessment: unchanged at 195 to 196**, **whole successful package: 485 to 490**, with **L >= 3 * T_s3 + C** and **remaining >= T_req + 3 * T_s3 + L**. **ADR-0019's amendment is now authoritative architecture**, and **the production implementation now conforms to that architecture offline**: **ADR-0018 offline implementation: MERGED / DORMANT**, **ADR-0019 production-code correction: MERGED / DORMANT / OFFLINE-CONFORMING** — **PR #48 merged**, merge commit **`f0b39fccdfb36ea69d08fb4def3979b87814b9ff`**, approved implementation head **`64dc3388f402ee98cf8940d94b42fa16aa7553e2`** — **the dormant acquisition implementation no longer uses the pre-ADR-0019 shared collision path**, **the ADR-0018-specific write-only publication surface now exists**, **the merged dormant acquisition implementation has zero acquisition HeadObject and zero acquisition GetObject**, and **the current dormant implementation is offline-conforming under the authoritative architecture**. **Before PR #48 merged the production implementation did not yet conform** — true then, and not rewritten. **The ADR-0019 implementation-correction prerequisite is SATISFIED**, and **satisfying the implementation prerequisite does not itself authorize or begin infrastructure work**: **further infrastructure design and mutation: NOT AUTHORIZED**, **Terraform / IAM: IMPLEMENTED AND APPLIED**, **qualification-principal deployment: PERFORMED**, **execution: ZERO**. **Acceptance of ADR-0019 is not authorization to implement or execute it.** **G1 OPEN · G2 OPEN**, no provider selected, Phase 3 **NOT COMPLETE**, CONTROL **DEFERRED**, live trading **HARD-DISABLED** |
| **[ADR-0020](docs/decisions/ADR-0020-request-scoped-qualification-payload-identity.md) — request-scoped qualification payload identity** | **ACCEPTED / IN FORCE** — PR #49 merged. Merge commit **`e4d328af53f2663c570f94e6c090c3296db8cb9d`**, approved ADR head **`d9bbb17b7f174c34223eb4736d763f115daf229f`**. **ADR-0020's conditional effectiveness event has occurred**, and **PR #49 was independently reviewed before its merge**. **While PR #49 was open, ADR-0020 was proposed and carried no authority**, and **ADR-0018 as amended by ADR-0019 governed the qualification payload identity before the PR #49 merge** — historical facts that stay true and are not rewritten. **The merge approved architecture only**, and authorized no production-code correction, no Terraform, no IAM, no infrastructure mutation, no deployment and no execution. It answers **the legitimate duplicate-payload collision** PR #48 exposed: a complete run is exactly 48 requests and 144 Bronze `PutObject`, the qualification payload object was content-addressed by `(provider, dataset, digest)`, and an acquisition-side 412 fails closed — so two legitimate byte-identical observations, such as ADR-0018's header-only page-two probes or an unchanged snapshot re-observed in Run B, derived one name and halted a correct run. **The scope is exactly one key class**: the claim and record keys already bind the request-scoped acquisition identity. Authoritative architecture: **the qualification payload key binds the execution identity, the request ordinal and the payload digest**, shaped `<qualification-payload-prefix>/<execution-identity>/requests/<NN>/sha256/<payload-digest>`, where **no provider subject value appears in a qualification payload key**, with a deterministic retry targeting the same key, and no random suffix, no listing and no preflight existence check. **Assessment reconstructs the qualification payload key and compares it exactly**, and **assessment recomputes SHA-256 over the retrieved payload bytes and refuses on any mismatch** before parsing. **ADR-0020 preserves ADR-0019's write-only collision policy unchanged** — **acquisition remains conditional `PutObject` only**, a 412 still establishes neither identical nor different content, and **`BRONZE_NAME_OCCUPIED` and `LOCATOR_NAME_OCCUPIED` are unchanged**. **ADR-0020 supersedes only the qualification payload-key identity rule**, **ADR-0020 does not supersede ADR-0017**, **ADR-0020 changes no shared general-purpose Bronze or S3ResearchObjectStore contract**, **ADR-0020 introduces no locator field**, **ADR-0020 introduces no additional S3 operation**, **ADR-0020 preserves the 485 to 490 package envelope** and **ADR-0020 preserves the deadline arithmetic L >= 3 * T_s3 + C**. **The architecture blocker that prevented ADR-0020 from being authoritative is resolved. The implementation blocker is resolved as well, offline.** **Architecture acceptance: COMPLETE**, **PR #48: merged**, merge commit **`f0b39fccdfb36ea69d08fb4def3979b87814b9ff`**, approved implementation head **`64dc3388f402ee98cf8940d94b42fa16aa7553e2`**, **PR #48 correction against ADR-0020: MERGED**, **production implementation: MERGED / DORMANT / OFFLINE-CONFORMING**, **ADR-0020 implementation: MERGED / DORMANT / OFFLINE-CONFORMING**, **a qualification payload-key builder exists**, and **ADR-0018 merged implementation: DORMANT / OFFLINE-CONFORMING**. **PR #48 was untouched by the ADR-0020 proposal and by its merge**, and it was corrected, independently reviewed and merged later, under a separate authorization. **While PR #48 was open it was not ready for review or merge and its correction had not begun** — true then, and not rewritten. **PR #48 is not defective for obeying ADR-0019** — its implementation work exposed the architectural identity gap, and the correction it required has since merged. **The ADR-0020 implementation-correction prerequisite is SATISFIED**, and **satisfying the implementation prerequisite does not itself authorize or begin infrastructure work** — **merging an implementation authorizes no infrastructure, no deployment and no run**, and **offline-conforming is not deployed, not active, not operational, not authorized to run and not empirically validated**. **Further infrastructure design and mutation: NOT AUTHORIZED · Terraform / IAM: IMPLEMENTED AND APPLIED · qualification-principal deployment: PERFORMED · execution: ZERO · Run A: NOT AUTHORIZED / NOT RUN · Run B: NOT AUTHORIZED / NOT RUN · combined assessment: NOT AUTHORIZED / NOT RUN.** **ADR-0019: ACCEPTED / IN FORCE · third ADR-0017 attempt: NOT AUTHORIZED · G1: OPEN · G2: OPEN · provider selected: NONE · Phase 3: NOT COMPLETE · CONTROL: DEFERRED · live trading: HARD-DISABLED** |
| **[ADR-0021](docs/decisions/ADR-0021-qualification-runtime-principal-and-trust-model.md) — qualification runtime principal and trust model** | **ACCEPTED / IN FORCE** — PR #54 merged. Merge commit **`c58d6c442c34928ad3c25f07368cf1e3323a6552`**, approved ADR head **`0b8d500699468a10c331219c694a8e2fb4e5adee`**, merged **2026-09-02T09:01:29Z**, with a **merge tree identical to the independently validated pull-request head tree**. **ADR-0021's conditional acceptance event has occurred**, and **PR #54 was independently reviewed before its merge**. **While PR #54 was open, ADR-0021 was proposed and carried no authority** — a historical fact about those days that stays true and is not rewritten. **The merge approved architecture only**, and **no implementation or operational authority followed from the merge**: it authorized no permission-set implementation, no Identity Center assignment, no policy attachment, no profile creation, no identity-gate or profile-constant correction, no Terraform, no IAM, no infrastructure mutation, no deployment and no execution. Authoritative architecture: **AWS IAM Identity Center is the human authentication root**, **no IAM user or long-lived access key is permitted for qualification**, **a dedicated, governed Identity Center operator group is the assignment subject**, and two permission sets — `KalpaManiQualificationAcquisition` and `KalpaManiQualificationAssessment` — are each assigned to that group in the single target account, each referencing only its merged PR #52 managed-policy declaration, and each reached through one of the two exact named profiles `kalpamani-qualification-acquisition` and `kalpamani-qualification-assessment`, with **session duration bounded to one hour per permission set**. **The identity gate binds the exact target account plus the exact permission-set role-name prefix and a validated AWS-generated suffix grammar**, **the profile name is routing input, not proof**, and **`sts:GetCallerIdentity` remains the runtime proof during a later authorized execution**. **ADR-0021 supersedes no prior ADR and amends no earlier ADR document**, and the arithmetic is unchanged — **acquisition PutObject: 145 to 147 · acquisition HeadObject: 0 · acquisition GetObject: 0 · two successful runs: 290 to 294 · assessment: 195 to 196 · whole successful package: 485 to 490 · L >= 3 * T_s3 + C · remaining >= T_req + 3 * T_s3 + L**. **Permission-set implementation: MERGED / APPLIED / 2 VERIFIED · Identity Center assignments: MERGED / APPLIED / 2 VERIFIED · generated Identity Center runtime roles: 2 VERIFIED · runtime trust principals: IDENTITY CENTER-OWNED / 2 VERIFIED · customer-managed-policy references: MERGED / APPLIED / 2 VERIFIED · governed acquisition profile: MATERIALIZED / IDENTITY PREFLIGHT PASSED · governed assessment profile: MATERIALIZED / IDENTITY PREFLIGHT PASSED · identity-gate/profile-constant correction: MERGED / NEVER EXERCISED AGAINST AWS · Organization-instance prerequisite: MET BY THE APPLIED DEPLOYMENT · AWS account/group/instance binding values: OWNER-SUPPLIED FOR THE APPLY / NOT RECORDED HERE · operator group: EXACTLY 1 OWNER-APPROVED HUMAN MEMBER / ASSIGNED · operator membership: MATERIALIZED / INDEPENDENTLY VERIFIED · profile crossover: NONE · membership/profile gate: COMPLETED · qualification-principal binding/deployment: COMPLETED · further Terraform and AWS/provider/credential access: NOT AUTHORIZED · further infrastructure mutation: NOT AUTHORIZED · qualification and binding-preflight execution: NOT AUTHORIZED / NOT RUN · Run A: NOT AUTHORIZED / NOT RUN · Run B: NOT AUTHORIZED / NOT RUN · combined assessment: NOT AUTHORIZED / NOT RUN · third ADR-0017 acquisition: NOT AUTHORIZED · sixth binding preflight: NOT AUTHORIZED · G1: OPEN · G2: OPEN · provider selected: NONE · Phase 3: NOT COMPLETE · CONTROL: DEFERRED · live trading: HARD-DISABLED** |
| **[ADR-0022](docs/decisions/ADR-0022-qualification-permission-set-name-limit.md) — qualification permission-set name limit** | **ACCEPTED / IN FORCE** — PR #57 merged. Merge commit **`b214484b0da6edd6192caa01c0e57a9878afc288`**, ordered parents **`f4aa4f89b4f41acdad57b96fe07e558e71ba40bd`** then **`63992a88a9c4fb64defdb446ccc29c5d43b3e0b3`**, merged **2026-09-02T15:39:27Z**, with a **merge tree identical to the independently validated pull-request head tree**. **ADR-0022's conditional acceptance event has occurred**, and **PR #57 was independently reviewed before its merge**. **While PR #57 was open, ADR-0022 was proposed and carried no authority** — a historical fact about those days that stays true and is not rewritten. **The merge approved architecture only**, and **no implementation or operational authority followed from the merge**. Authoritative architecture: the acquisition permission-set name is **`KalpaManiQualificationAcquire`**, exactly 29 characters and buildable by the pinned `hashicorp/aws` v6.62.0 `aws_ssoadmin_permission_set` name validator; `KalpaManiQualificationAcquisition` is **retired**, historical and defect context, and never the current name; the assessment permission-set name **`KalpaManiQualificationAssessment` is unchanged**; both governed profile names `kalpamani-qualification-acquisition` and `kalpamani-qualification-assessment` are **unchanged**; actor semantics, the one-hour session duration, the suffix grammar, exact-account plus actor-specific role-name prefix verification, **structure-not-provenance** and the refusal to pin a full generated ARN are each **unchanged**; and the acquisition generated-role prefix is now `AWSReservedSSO_KalpaManiQualificationAcquire_`. **ADR-0022 amends only that one value** — **ADR-0017 isolation, ADR-0019 write-only acquisition, ADR-0020 request-scoped payload identity and assessment digest verification are unchanged**, and so is the arithmetic — **acquisition PutObject: 145 to 147 · acquisition HeadObject: 0 · acquisition GetObject: 0 · two successful runs: 290 to 294 · assessment: 195 to 196 · whole successful package: 485 to 490 · L >= 3 * T_s3 + C · remaining >= T_req + 3 * T_s3 + L**. **PR #56: MERGED · PR #56 correction: MERGED** — the later, separately authorized correction replaced the retired name consistently and added a provider 1-32 name-length guard, and the **genuine isolated `terraform validate` against the pinned provider was performed in task-owned external copies before that merge**. **Implementation: MERGED / APPLIED / 2 VERIFIED · Terraform: APPLIED (PR #60, controlled saved-plan apply) · permission-set implementation: MERGED / APPLIED / 2 VERIFIED · Identity Center assignments: MERGED / APPLIED / 2 VERIFIED · generated Identity Center runtime roles: 2 VERIFIED · customer-managed-policy references: MERGED / APPLIED / 2 VERIFIED · governed acquisition profile: MATERIALIZED / IDENTITY PREFLIGHT PASSED · governed assessment profile: MATERIALIZED / IDENTITY PREFLIGHT PASSED · Organization-instance prerequisite: MET BY THE APPLIED DEPLOYMENT · further AWS discovery: NOT AUTHORIZED · AWS account/group/instance binding values: OWNER-SUPPLIED FOR THE APPLY / NOT RECORDED HERE · operator group: EXACTLY 1 OWNER-APPROVED HUMAN MEMBER / ASSIGNED · operator membership: MATERIALIZED / INDEPENDENTLY VERIFIED · profile crossover: NONE · membership/profile gate: COMPLETED · qualification-principal deployment: COMPLETED · further infrastructure mutation: NOT AUTHORIZED · Terraform isolated init/validate: PERFORMED IN EXTERNAL COPIES ONLY · Terraform plan/apply: PERFORMED ONCE UNDER SEPARATE AUTHORIZATION · qualification and binding-preflight execution: NOT AUTHORIZED / NOT RUN · Run A / Run B / combined assessment: NOT AUTHORIZED / NOT RUN · third ADR-0017 acquisition: NOT AUTHORIZED · sixth binding preflight: NOT AUTHORIZED · G1: OPEN · G2: OPEN · provider selected: NONE · Phase 3: NOT COMPLETE · CONTROL: DEFERRED · live trading: HARD-DISABLED** |
| **Applied qualification infrastructure — PR #60, controlled saved-plan apply** | **APPLIED / INDEPENDENTLY VERIFIED** — the **controlled saved-plan apply COMPLETED** and an **independent post-apply verification PASSED**: **live customer-managed IAM policies 2 VERIFIED · live Identity Center permission sets 2 VERIFIED · live customer-managed-policy references 2 VERIFIED · live account assignments 2 VERIFIED · generated Identity Center runtime roles 2 VERIFIED**. **Infrastructure existence is not qualification success**, and **materialized access is not authority to use it** — the operator and profile state recorded on the day of the apply has since been superseded, and the governing record is *The qualified operator access*: **operator group EXACTLY 1 OWNER-APPROVED HUMAN MEMBER / ASSIGNED**, **operator membership MATERIALIZED / INDEPENDENTLY VERIFIED**, **governed acquisition profile MATERIALIZED / IDENTITY PREFLIGHT PASSED**, **governed assessment profile MATERIALIZED / IDENTITY PREFLIGHT PASSED**, **profile crossover NONE**, **AWS config ACL EFFECTIVE ACCESS PRESERVED**, **membership/profile gate COMPLETED**, **sixth private-binding preflight NOT AUTHORIZED / NOT RUN**, **provider credential retrieval NONE**, **S3/provider activity NONE**, **further infrastructure mutation NOT AUTHORIZED**, **qualification and binding-preflight execution NOT AUTHORIZED / NOT RUN**, **third ADR-0017 acquisition NOT AUTHORIZED / NOT RUN**, **Run A / Run B / combined assessment NOT AUTHORIZED / NOT RUN**, **provider acquisition NOT AUTHORIZED / NOT RUN**, **backtesting NOT STARTED**, **G1 OPEN · G2 OPEN**, **provider selected NONE**, **Phase 3 NOT COMPLETE**, **CONTROL DEFERRED**, **live trading HARD-DISABLED** |
| **Qualified operator access — membership and governed profiles** | **MATERIALIZED / INDEPENDENTLY VERIFIED** — one owner-approved human operator was added to the governed Identity Center group, both governed AWS profiles were materialized, and an **independent review read the result rather than producing it**: **operator selection OWNER-APPROVED · operator group EXACTLY 1 OWNER-APPROVED HUMAN MEMBER / ASSIGNED · operator membership MATERIALIZED / INDEPENDENTLY VERIFIED · governed acquisition profile MATERIALIZED / IDENTITY PREFLIGHT PASSED · governed assessment profile MATERIALIZED / IDENTITY PREFLIGHT PASSED · profile crossover NONE · AWS config ACL EFFECTIVE ACCESS PRESERVED · membership/profile gate COMPLETED**. **Who the operator is stays out of this repository** — the count is recorded and the person is not. **Materialized access is not authority to use it**: **sixth private-binding preflight NOT AUTHORIZED / NOT RUN · provider credential retrieval NONE · S3/provider activity NONE · qualification execution NOT AUTHORIZED / NOT RUN · third ADR-0017 acquisition NOT AUTHORIZED / NOT RUN · Run A / Run B / combined assessment NOT AUTHORIZED / NOT RUN · further infrastructure mutation NOT AUTHORIZED · backtesting NOT STARTED · G1 OPEN · G2 OPEN · provider selected NONE · Phase 3 NOT COMPLETE · CONTROL DEFERRED · live trading HARD-DISABLED** |
| **Ingestion runner · ECS task or image · a third authenticated qualification attempt** | **NOT AUTHORIZED** — two attempts occurred, the first refusing at the AWS identity gate and the second completing, and neither authorizes anything further |
| **ADR-0018 implementation execution · qualification infrastructure deployment · the two new IAM roles · Run A · Run B · the combined assessment run** | **NOT AUTHORIZED** — ADR-0018 is **ACCEPTED / IN FORCE**, and **the merge approved architecture only**. **ADR-0018 implementation execution: NOT AUTHORIZED · infrastructure mutation: NOT AUTHORIZED · Run A: NOT AUTHORIZED · Run B: NOT AUTHORIZED · assessment: NOT AUTHORIZED.** **Implementation, infrastructure mutation and execution stay three separate gates and are never collapsed into one.** **The ADR-0018 offline implementation is MERGED and DORMANT — PR #41 merged**, merge commit **`3ddd7d40741bb9a50ae4fc5452324ddbfb5e1ec0`**, approved implementation head **`96daac7963d936f231b37847579c5f28bb313760`**; and **the fixed 48-request assessment-boundary correction is MERGED — PR #44 merged**, merge commit **`c945970613b80bfd4f42acc4f3acb4814895eb42`**, approved correction head **`78b4425077e65eeb12dfd24b35825741370e0e0f`**. It was built, and then corrected, under **later, separate written authorizations for offline construction, offline correction and offline validation only**: **synthetic fixtures and offline tests only**, **zero** AWS, credential, Secrets Manager, provider, S3, Terraform and IAM operations, and **neither entry point has ever been run**. **The offline implementation is merged, dormant and never executed**, and **merging an implementation authorized no execution, no infrastructure deployment and no run**. **The clarification amendment is EFFECTIVE — PR #42 merged**, its **conditional effectiveness event has occurred**, and it **authorizes none of the later gates**. **SUPERSEDED IN PART — Run A has since COMPLETED once, on 2026-09-04, under its own separate written authorization; the completed Run A empirical acquisition section governs, and a Run A retry, Run B and the combined assessment stay NOT AUTHORIZED / NOT RUN.** |
| **CONTROL-classification publication** | **DEFERRED / NOT AUTHORIZED** |
| **Provider purchase — qualification subscription** | **PURCHASED / ACTIVE (2026-08-28, ADR-0010)** |
| **Provider credential state · repository consumption · provider API access · Services Data** | Provider credential state **OWNER API KEY EXISTS / OWNER-ATTESTED / RETRIEVED ONCE BY THE ENTRY POINT AND STRUCTURALLY ACCEPTED / NOT VERIFIED AGAINST SHARADAR**; repository/application credential retrieval **ONE, on the fifth authorized binding-preflight attempt**, consumption **offline composition only**, and **any additional retrieval NOT AUTHORIZED**; provider API access **NOT AUTHORIZED**; Services Data access and ingestion **NOT AUTHORIZED**; a **third** authenticated qualification attempt **NOT AUTHORIZED** — the first refused at the AWS identity gate and retrieved no credential, and the second completed with **one provider request** and **provider-wide authentication still UNKNOWN** — an owner-held key is not repository access, a subscription existing is not permission to use it, and a structurally accepted secret is not a credential proven to authenticate against Sharadar, which stays **UNKNOWN** |
| **ADR-0018 empirical acquisition — Run A** | **COMPLETED ONCE (2026-09-04)** — one entry-point invocation, exit code **0**, closed public outcome **`empirical acquisition completed`**, **48 provider requests**, **zero provider retries**, **145 append-only licensed-S3 writes**, **zero conditional HeadObject**, **zero object-byte GetObject**, **zero listing operations**, **zero CONTROL operations**, **one `GetSecretValue`**, **zero Terraform operations**, **two `sts:GetCallerIdentity` invocations**, the locator **published last and addressable**, **145 objects newly written**, and the execution identifier **permanently retired**. **A command outcome, not a provider verdict** — **P1–P9 UNEVALUATED**, **a Run A retry NOT AUTHORIZED / NOT RUN**, **Run B NOT AUTHORIZED / NOT RUN** and at least **eight calendar days** after Run A with an earliest approved target of **2026-09-12**, **combined assessment NOT AUTHORIZED / NOT RUN**, **G1 / G2 OPEN**, **provider selected NONE**, **Phase 3 NOT COMPLETE**, **CONTROL DEFERRED**, **live trading HARD-DISABLED** |
| **Real external-data acquisition** | **ONE PROVIDER REQUEST** by the second authenticated qualification attempt, with **one complete retained acquisition record** — attempt-two S3 qualification operations are **THREE TO SIX**, and how many objects were newly written is **NOT ESTABLISHED**. **Run A has since COMPLETED once, on 2026-09-04 — 48 provider requests, zero provider retries, 145 append-only licensed-S3 writes, zero object-byte reads, zero listings and zero CONTROL operations — and it is a command outcome, not a provider verdict.** Production ingestion, backfill and update **NOT STARTED / NOT AUTHORIZED** |
| **Short research** | **NOT AUTHORIZED** |
| **[ADR-0026](docs/decisions/ADR-0026-strategy-brain-architecture-and-governance.md) — Strategy Brain architecture and governance** | **ACCEPTED — EFFECTIVE ON MERGE OF PR #70**, and **PROPOSED — NOT IN FORCE** until that merge. It introduces [`docs/phase4/strategy-brain-specification.md`](docs/phase4/strategy-brain-specification.md) as **specification only**. On that merge it accepts **architecture, contracts, governance and future implementation boundaries** and **nothing else** — **Brain runtime implementation NOT AUTHORIZED · strategy, factor, scanner and AI-agent implementation NOT AUTHORIZED · portfolio and risk engine implementation NOT AUTHORIZED · backtesting NOT AUTHORIZED · provider data usage NOT AUTHORIZED · broker activity NOT AUTHORIZED · capital change NOT AUTHORIZED**. It **amends and supersedes no ADR**, refining ADR-0006 §D and §E into checkable contracts, and it **closes no gate** — **G1 OPEN · G2 OPEN · G4-G7 OPEN**. **No alpha is claimed**, and **no `src/` module is created by it** |
| **[ADR-0027](docs/decisions/ADR-0027-cockpit-and-feedback-architecture-and-governance.md) — Cockpit and Feedback architecture and governance** | **ACCEPTED — EFFECTIVE ON MERGE OF PR #71**, and **PROPOSED — NOT IN FORCE** until that merge. It introduces [`docs/architecture/COCKPIT_FEEDBACK_EXTENSION.md`](docs/architecture/COCKPIT_FEEDBACK_EXTENSION.md) and the five documents under [`docs/cockpit/`](docs/cockpit/cockpit-v1-specification.md) as **specification only**. On that merge it accepts **architecture, contracts, governance and future implementation boundaries** and **nothing else** — **Cockpit application implementation NOT AUTHORIZED · read-model, projection and API implementation NOT AUTHORIZED · feedback and learning-engine implementation NOT AUTHORIZED · database, migration, scheduler and deployment NOT AUTHORIZED · dependency installation NOT AUTHORIZED · provider, AWS and broker activity NOT AUTHORIZED · capital, risk and strategy change NOT AUTHORIZED**. **V1 is observational** — no order, stop, risk, capital, strategy, provider, Run B, assessment, CONTROL or authoritative governance mutation, and **every future control is inert with no handler and no control API route**. It **amends and supersedes no ADR**, consumes ADR-0026 unchanged, and it **closes no gate** — **G1 OPEN · G2 OPEN · G4-G7 OPEN**. **No alpha is claimed**, **no `src/` module is created by it**, and **no Blueprint PDF is edited** |
| **Strategies / Brain / AI / portfolio / risk** | **NOT IMPLEMENTED / NOT AUTHORIZED** — the Brain is **specified** under ADR-0026, accepted effective on merge of PR #70, and **not implemented**; a specification is not an implementation |
| **Cockpit / read models / feedback engine** | **NOT IMPLEMENTED / NOT AUTHORIZED** — the Cockpit is **specified** under ADR-0027, accepted effective on merge, and **not implemented**; no application, read API, projection, database or feedback automation exists, and a specification is not an implementation |
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

**The control is absence in the platform, and one authorized boundary outside it.** No credential
is retrieved, inspected, created, configured or bound anywhere under `src/`; no bucket identifier is
recorded here; and **no module under `src/` constructs an SDK client**. The store **is** called now
— by the dormant qualification runtime (ADR-0012), on an injected store — and it is now also
*constructed*, by the dormant composition root
([ADR-0014](docs/decisions/ADR-0014-implement-the-dormant-sharadar-qualification-composition-root.md)),
from an injected client and a caller-supplied bucket string. **What is absent from the adapter and
from the platform is what would make either real there**: a credential source, a real credential, a
constructed SDK client, a runner, and any code that calls something other than the offline
preflight. Each is verified by a static test rather than asserted here.

**One boundary outside `src/` has now supplied real values, once.** The ADR-0015 operator entry
point is the sole permitted construction site, and the **fifth separately authorized
binding-preflight attempt** ran it: it retrieved **one** credential, constructed **one** S3 client,
resolved the governed licensed bucket **once**, and made **one** offline composition preflight.
**It performed zero S3 object operations and sent zero provider requests**, so the adapter's own
`put_object` and `head_object` have still never run against AWS. That is a fact about the entry
point, not a relaxation of the platform boundary, which is unchanged.

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
removal is accepted. **A real Sharadar qualification run remains NOT AUTHORIZED and has never
happened** — one authenticated attempt has since been made under a separate authorization and
refused at the AWS identity gate, before any provider contact —
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
classified, whether it was configured at all **remained unknown at that point** — that run could
not say, and nothing here guesses backwards. **The fifth attempt later resolved the identifier
once**, which is recorded in the binding section and does not revise what this run established.

```
outcome                                       identifier   client   invocations
authorization / profile / identity / bucket            0        0             0
secrets-boundary import refusal                        0        0             0
REFUSED_SECRET_IDENTIFIER                              1        0             0
REFUSED_DEPENDENCY at client construction              1        1             0
REFUSED_CREDENTIAL                                     1        1             1
REFUSED_DEPENDENCY after the credential                1        1             1
completed synthetic offline preflight                  1        1             1

get_secret_value invocations by this repository: ONE -- admitted, on the fifth attempt
Secrets Manager client constructions: ONE -- on the fifth attempt
Secrets Manager underlying network requests: UNKNOWN
S3 client constructions: ONE   ·   S3 object operations: ZERO
provider transport constructions: ONE   ·   Sharadar/provider requests: ZERO
AWS identity-gate activity: OCCURRED -- total AWS activity was not zero
real credential retrieval: ONE -- STRUCTURALLY ACCEPTED
Sharadar authentication by that credential: UNKNOWN -- NO PROVIDER REQUEST WAS MADE
operational environment synchronized: DONE AND VERIFIED -- see the environment section
Python dependency lock: ABSENT   ·   environment: RANGE-CONFORMANT, NOT LOCK-CONFORMANT
a sixth binding-preflight attempt: NOT AUTHORIZED
additional credential or Secrets Manager access: NOT AUTHORIZED
a third authenticated qualification attempt: NOT AUTHORIZED -- two occurred; the
    first refused at the AWS identity gate with REFUSED_IDENTITY, exit code 6,
    and the second COMPLETED with exit code 0
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
one future bounded attempt            AUTHORIZED, RUN AND COMPLETED -- the fifth attempt
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
**not** resolved by recording it. The provisional acceptance of the exact validated fingerprint
above was granted for **one** bounded binding-preflight diagnostic; **that one has since been run —
the fifth attempt — so the provisional acceptance is spent.** It was **not** approval for
production qualification, ingestion, CONTROL publication or live operation, and it is not approval
for a sixth attempt.

**A usable environment is not a permission.** Everything the earlier slices established is unchanged,
and the boundaries below are restated rather than relaxed:

```
binding-preflight entry point         SOLE PERMITTED SDK/CLIENT-CONSTRUCTION BOUNDARY
licensed-bucket resolutions: ONE   ·   S3 client constructions: ONE   ·   S3 object operations: ZERO
"real bucket binding": UNDEFINED IN THIS REPOSITORY -- STATED AS THE THREE FACTS ABOVE
operational secret-identifier configuration: OWNER-CONFIGURED, AND RESOLVED ONCE BY THE ENTRY POINT
authorized binding-preflight attempts to date: FIVE -- the first four refused, the fifth completed
fifth attempt: COMPLETED + VALIDATION_COMPLETED -- exit code 0, stage 10, VALIDATED_OFFLINE
authorized AWS SSO-login attempts to date: TWO -- the first refused, the second succeeded
first AWS SSO-login attempt: REFUSED_SSO_LOGIN, timed out at 420s
corrected AWS SSO-login attempt: SUCCESSFUL -- live console, exit code 0
successful governed SSO refreshes: ONE   ·   sanitized identity confirmations after it: ONE, SUCCESSFUL
identity status: CONFIRMED AT THE TIME OF THAT COMMAND -- future session validity NOT GUARANTEED
identity-confirmation underlying AWS network requests: UNKNOWN
Secrets Manager client constructions: ONE   ·   get_secret_value invocations: ONE
Secrets Manager underlying network requests: UNKNOWN   ·   S3 object operations: ZERO
binding-preflight Sharadar/provider requests: ZERO   ·   credential retrieved: ONE
binding-preflight qualification runs: ZERO
authenticated qualification attempts: TWO -- one REFUSED, one COMPLETED
known provider requests: ONE   ·   exact-request authentication: ESTABLISHED
provider-wide authentication: UNKNOWN
attempt-two S3 qualification operations: THREE TO SIX -- three PutObject, zero to three HeadObject
attempt-two newly written objects: NOT ESTABLISHED
credential status: STRUCTURALLY ACCEPTED   ·   Sharadar authentication: UNKNOWN
AWS credential-provider chain invoked during environment verification: NONE
AWS requests during environment verification: ZERO
binding preflight or composition preflight run during environment verification: NEITHER
composition preflight run: ONCE -- by the fifth binding-preflight attempt, offline
a sixth binding-preflight attempt: NOT AUTHORIZED
further AWS authentication diagnosis: NOT AUTHORIZED
another AWS SSO-login/refresh attempt: SEPARATELY GATED / NOT AUTHORIZED
additional credential or Secrets Manager access: NOT AUTHORIZED
a third authenticated qualification attempt: NOT AUTHORIZED -- two occurred, the
    first refusing at the AWS identity gate and the second COMPLETING
further Sharadar/provider access: NOT AUTHORIZED
S3 object operations or publication: NOT AUTHORIZED
ingestion, backfill and update: NOT AUTHORIZED
CONTROL publication: DEFERRED / NOT AUTHORIZED
broker, LEAN, Paper and live trading: NOT AUTHORIZED -- live trading HARD-DISABLED
further dependency installation or environment resynchronization: SEPARATELY GATED
```

Environment verification imported `boto3` and `botocore` with socket constructors replaced by raising
stubs and `builtins.open` recording every path opened: **no socket was created, no file under an
`.aws` directory was opened, `boto3.DEFAULT_SESSION` stayed `None`**, and `boto3.client` was checked
for existence by attribute lookup and never called. No environment-variable value, AWS profile, SSO
cache, credential, account identifier, bucket value or secret identifier was read.

**THE ONE AUTHORIZED ATTEMPT THIS ENVIRONMENT WAS READY FOR HAS BEEN RUN** — the fifth, which
completed. That is a statement about what happened on this machine, not a permission for the next
thing. **G1 OPEN · G2 OPEN · G3 CLOSED · G4–G7 OPEN**, ADR-0005 **PROPOSED**, INC-0002 **OPEN**,
Phase 3 **NOT COMPLETE**, CONTROL publication **DEFERRED**, live trading **HARD-DISABLED**.

### The Sharadar private-binding preflight — refused by default, four times refused, then completed

[ADR-0015](docs/decisions/ADR-0015-implement-the-dormant-sharadar-private-binding-preflight.md) authorized the last piece nobody had written: the path that will eventually
supply the private bindings every accepted slice takes by injection. One operator entry point,
`scripts/sharadar_binding_preflight.py`, and one boundary module,
`data/ingest/sharadar/secrets.py`.

**Status: ACCEPTED / IN FORCE — PR #22 merged.** **Merging it bound nothing** — but the entry
point has since been run **five** times. **Four separately authorized operator attempts occurred and
all four refused** — one at the AWS identity gate, one on a missing AWS SDK dependency, one at the
fixed secret-identifier source, and — after the owner's secret creation and identifier
configuration — one again at the AWS identity gate with **`REFUSED_IDENTITY`**. **The fifth
separately authorized attempt then completed**: **exit code `0`**, closed outcome
**`COMPLETED + VALIDATION_COMPLETED`**, and one offline `preflight_qualification_composition`
invocation that returned **`VALIDATED_OFFLINE`**. **A credential was retrieved and structurally
accepted.** **No provider was accessed, no S3 object operation occurred, and no qualification
execution or ingestion occurred.**

**The chronology, in order.** Each step was separately authorized, and none of them authorized the
next:

1. **Four separately authorized binding-preflight attempts occurred and all four refused.**
2. **Attempt 4 refused at the AWS identity gate** with `REFUSED_IDENTITY`.
3. **The later standalone diagnosis classified the SSO session
   `REFUSED_SSO_SESSION_MISSING_OR_EXPIRED`**, without distinguishing missing from expired.
4. **A later corrected SSO refresh completed successfully.**
5. **A sanitized identity-confirmation command returned `IDENTITY_CONFIRMED`**, without
   guaranteeing future session validity.
6. **The fifth separately authorized binding-preflight attempt then ran exactly once.**
7. **It exited `0`** and emitted exactly `binding preflight completed` and
   `offline validation completed`.
8. **Its closed outcome was `COMPLETED + VALIDATION_COMPLETED`.**
9. **Its last definitively reached stage was stage 10**: one
   `preflight_qualification_composition` invocation that returned `VALIDATED_OFFLINE`.

**The first four refusals remain refusals.** They are historical facts about what happened on those
days, and the fifth attempt's completion converts none of them into a success.

**A credential was retrieved, and that is not provider authentication.** One admitted
`get_secret_value` returned a `SecretString`, the existing credential contract **accepted it
structurally**, and it was passed into the offline composition. **No credential or fragment was
displayed, logged, persisted, hashed, fingerprinted, measured or summarized.** *Usable* here means
**structurally acceptable to the existing contract** and nothing more: **whether it authenticates
successfully against Sharadar remains UNKNOWN**, because **no Sharadar or provider request
occurred**. **Owner attestation and successful repository retrieval are not the same as provider
authentication.**

**The bucket is recorded as facts, not as a binding verdict.** The fifth attempt **resolved the
governed licensed bucket once** and **constructed one S3 client**, and performed **zero S3 object
operations**. This repository's phrase *real bucket binding* is **ambiguous**: the composition root
reports `real bucket binding: NONE` while constructing a store from a caller-supplied bucket string,
and the ADR-0011 section lists *a constructed SDK client* and *a bound bucket* as two separate
absent items without ever naming the act that produces the second. Nothing tracked fixes the
threshold, so the status records **bucket resolutions ONE · S3 client constructions ONE · S3 object
operations ZERO**, and claims **neither a real binding nor its absence**.

```
entry points          ONE      scripts/ only; the installed package re-exports nothing
default behaviour     REFUSE   no flag, no work -- no lookup, no client, no socket, no read
authorization         ONE      --i-am-the-operator-authorizing-binding-preflight
what it authorizes    BINDING PREFLIGHT ONLY -- never a qualification run
authorized attempts   FIVE     the first four refused; the fifth completed
first four attempts   REFUSED  none of them reached a Secrets Manager client
fifth attempt         COMPLETED + VALIDATION_COMPLETED -- exit code 0
third attempt         REFUSED_SECRET_IDENTIFIER at the fixed secret-identifier source
fourth attempt        REFUSED_IDENTITY at the AWS identity gate
AWS identity-gate activity: OCCURRED -- total AWS activity was not zero
identity-gate invocations on the fourth attempt: ONE -- it did not pass
STS command invocations on the fourth attempt: UNKNOWN -- real pre-STS refusal paths exist
standalone diagnostic commands during the fourth attempt: ZERO
AWS network requests on the fourth attempt: UNKNOWN -- no numeric count is established
post-fourth AWS identity diagnosis: COMPLETED -- REFUSED_SSO_SESSION_MISSING_OR_EXPIRED
diagnosis process invocations: ONE   ·   STS command invocations: ONE   ·   exit code: 255
diagnosis underlying AWS network requests: UNKNOWN
missing vs expired: NOT DISTINGUISHED by the diagnosis
governed profile: PINNED IN THE CHILD ENVIRONMENT, NEVER DISCLOSED
SSO-login invocations during the diagnosis: ZERO   ·   repair actions during it: ZERO
fifth binding-preflight attempts at that point: ZERO
authorized AWS SSO-login attempts to date: TWO -- the first refused, the second succeeded
first post-diagnosis AWS SSO-login attempt: COMPLETED -- REFUSED_SSO_LOGIN
first SSO-login command invocations: ONE   ·   command: aws sso login --no-cli-pager
first SSO-login exit code: NOT AVAILABLE / PROCESS TERMINATED ON TIMEOUT
first SSO-login timeout: 420 SECONDS   ·   lingering AWS CLI process: NONE
first attempt browser authorization interactions: ZERO   ·   device authorizations completed: ZERO
SSO refreshes achieved by the first attempt: ZERO   ·   SSO session after it: STILL UNREFRESHED
first SSO-login underlying AWS network requests: UNKNOWN
identity-confirmation command invocations after the first attempt: ZERO
first attempt likely cause: INTERACTIVE BROWSER/DEVICE-CODE SURFACE SUPPRESSED -- LIKELY, NOT PROVEN
device URL or code in the first attempt's undisplayed buffer: UNKNOWN -- NOT INSPECTED
corrected AWS SSO-login attempt: COMPLETED -- SUCCESSFUL
corrected SSO-login command invocations: ONE   ·   command: aws sso login --no-cli-pager
corrected SSO-login session: A NEW CLAUDE SESSION
corrected SSO-login output handling: LIVE CONSOLE -- INHERITED STDIN, STDOUT AND STDERR
corrected SSO-login capture, pipe, redirect, buffer or file: NONE
corrected SSO-login interactive browser/device flow: COMPLETED
corrected SSO-login exit code: 0   ·   lingering AWS CLI process: NONE
successful governed SSO refreshes: ONE
corrected SSO-login underlying AWS network requests: UNKNOWN
corrected child environment: MINIMAL AND ALLOWLISTED, BUILT KEY-BY-KEY
whole-environment copy during the corrected attempt: NONE
credential-bearing ambient variables copied or inspected during it: NONE
governed profile source: STATIC AST PARSE OF EXPECTED_PROFILE, NEVER DISCLOSED
entry-point module imported or executed by either SSO operation: NEITHER
verification URL and one-time device code: TRANSIENT IN THE LIVE CONSOLE ONLY -- NOT REPEATED, NOT PERSISTED
sanitized identity confirmations after the corrected refresh: ONE -- SUCCESSFUL
identity-confirmation command: aws sts get-caller-identity --no-cli-pager --output json
identity-confirmation exit code: 0   ·   classification: IDENTITY_CONFIRMED
identity-confirmation response: UserId, Account AND Arn STRUCTURALLY PRESENT AND NON-EMPTY
raw identity response and private identity values: NOT DISPLAYED, NOT PERSISTED
captured identity buffers: CLEARED AFTER CLASSIFICATION
identity-confirmation underlying AWS network requests: UNKNOWN
identity status: CONFIRMED AT THE TIME OF THAT COMMAND
current or future session validity: NOT GUARANTEED BY THAT HISTORICAL CONFIRMATION
KALPAMANI_SHARADAR_SECRET_ID reads by the corrected SSO session: ZERO
fifth binding-preflight attempts immediately after the corrected refresh: ZERO
fifth binding-preflight attempt: COMPLETED -- run later, under its own authorization
fifth attempt process invocations: ONE   ·   exit code: 0
fifth attempt public output: binding preflight completed / offline validation completed
fifth attempt closed outcome: COMPLETED + VALIDATION_COMPLETED
fifth attempt last stage definitively reached: STAGE 10 -- offline composition preflight
fifth attempt composition status: VALIDATED_OFFLINE
fifth attempt identity-gate invocations: ONE -- PASSED
fifth attempt licensed-bucket resolutions: ONE
fifth attempt secret-identifier resolutions: ONE
fifth attempt Secrets Manager client constructions: ONE
fifth attempt get_secret_value invocations: ONE -- ADMITTED
fifth attempt S3 client constructions: ONE   ·   S3 object operations: ZERO
fifth attempt provider transport constructions: ONE   ·   Sharadar/provider requests: ZERO
fifth attempt offline composition-preflight invocations: ONE
fifth attempt qualification executions: ZERO
fifth attempt underlying AWS network requests: UNKNOWN
fifth attempt credential: RETRIEVED -- ONE SecretString, STRUCTURALLY ACCEPTED
credential display, log, persistence, hash, fingerprint or measurement: NONE
"usable" means: STRUCTURALLY ACCEPTABLE TO THE EXISTING CREDENTIAL CONTRACT
Sharadar authentication by that credential: UNKNOWN -- NO PROVIDER REQUEST WAS MADE
operational secret-identifier configuration: OWNER-CONFIGURED, AND RESOLVED ONCE BY THE ENTRY POINT
owner credential setup occurred AFTER the third attempt and BEFORE the fourth
identifier-source resolutions on the third attempt: ONE
identifier-source resolutions on the fourth attempt: ZERO
identifier-source resolutions on the fifth attempt: ONE
licensed-bucket resolutions on the fourth attempt: ZERO
licensed-bucket resolutions on the fifth attempt: ONE
KALPAMANI_SHARADAR_SECRET_ID read by the fourth attempt: NO
KALPAMANI_SHARADAR_SECRET_ID read by the fifth attempt: YES -- ONCE, NEVER DISCLOSED
Secrets Manager client constructions: ONE
get_secret_value invocations: ONE
Secrets Manager underlying network requests: UNKNOWN
S3 client constructions: ONE   ·   S3 object operations: ZERO
provider transport constructions: ONE   ·   Sharadar/provider requests: ZERO
offline composition-preflight invocations: ONE
credential retrieval: ONE   ·   binding-preflight qualification runs: ZERO
owner-side Secrets Manager secret creation: ATTESTED, AND READ ONCE BY THE ENTRY POINT
Secrets Manager secret reads by this repository: ONE
"real bucket binding": UNDEFINED IN THIS REPOSITORY -- STATED AS BUCKET RESOLUTION ONE,
                       S3 CLIENT CONSTRUCTION ONE, S3 OBJECT OPERATIONS ZERO
qualification-run execution surface: NONE
provider-fetch operation: NONE   ·   object-publication operation: NONE
runner, task, image, scheduler or service: NONE
sixth binding-preflight attempt: NOT AUTHORIZED
further AWS authentication diagnosis: NOT AUTHORIZED
another AWS SSO-login/refresh attempt: SEPARATELY GATED / NOT AUTHORIZED
further environment resynchronization: SEPARATELY GATED / NOT AUTHORIZED
additional credential or Secrets Manager access: NOT AUTHORIZED
a third authenticated qualification attempt: NOT AUTHORIZED -- two occurred; the
    first refused at the AWS identity gate with REFUSED_IDENTITY, exit code 6,
    and the second COMPLETED with exit code 0
further Sharadar/provider access: NOT AUTHORIZED
S3 object operations or publication: NOT AUTHORIZED
ingestion, backfill and update: NOT AUTHORIZED
CONTROL publication: DEFERRED / NOT AUTHORIZED
broker, LEAN, Paper and live trading: NOT AUTHORIZED -- live trading HARD-DISABLED
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
| **owner credential setup, after the third attempt** | the owner attests that an AWS Secrets Manager secret was created for the existing Sharadar API key and that `KALPAMANI_SHARADAR_SECRET_ID` was configured. **OWNER-CONFIGURED, AND NOT YET VERIFIED BY ANY ENTRY-POINT RUN AT THAT TIME** — the fifth attempt, later and separately authorized, is what resolved it |
| **fourth authorized attempt**, after that setup | one process invocation, from a fresh post-restart process. Passed operator authorization and the governed profile contract, **invoked the application AWS identity gate once**, and refused there with **`REFUSED_IDENTITY`** — public output `binding preflight refused: the AWS identity gate did not pass`, exit code 1. It **never reached licensed-bucket resolution and never reached the secret-identifier source**, so it did not read `KALPAMANI_SHARADAR_SECRET_ID`, constructed no AWS service client and retrieved no credential. **No retry and no standalone authentication diagnosis followed** |
| **a second, separately authorized diagnosis**, after the fourth attempt and after PR #28 merged | **one** process invocation of **one** `aws sts get-caller-identity` command, exit code **255**, closed outcome **`REFUSED_SSO_SESSION_MISSING_OR_EXPIRED`** — the governed SSO session or cached token was classified unavailable or expired, and the classification **does not distinguish missing from expired**. The governed profile was pinned in the child environment and never disclosed; no identity, raw output or error text was disclosed or persisted. Its **own** underlying AWS network-request count is **UNKNOWN**. **Nothing followed it under that authorization: no retry, no `aws sso login`, no authentication repair, no identity-gate invocation and no fifth attempt** |
| **a separately authorized AWS SSO-login attempt**, after that diagnosis and after PR #29 merged | **one** process invocation of **one** `aws sso login --no-cli-pager` command, the governed profile resolved by static AST parse of the tracked `EXPECTED_PROFILE` constant and pinned in the child environment only, never disclosed. It **timed out after 420 seconds**, was terminated and left **no lingering AWS CLI process**, so **no exit status was returned** — the closed outcome is **`REFUSED_SSO_LOGIN`**. **Browser authorization interactions ZERO**, **device authorizations completed ZERO**, **successful SSO refreshes ZERO**, **identity-confirmation command invocations ZERO**, **fifth binding-preflight attempts ZERO**; its underlying AWS network-request count is **UNKNOWN**. The SSO session **remained unrefreshed** |
| **a corrected, separately authorized AWS SSO-login attempt**, in a new Claude session after PR #30 merged | **one** process invocation of **one** `aws sso login --no-cli-pager` command, run on a **live console with inherited stdin, stdout and stderr** — nothing captured, piped, redirected, buffered or written to a file. The **interactive browser/device flow completed**, the command **exited `0`**, **successful governed SSO refreshes became ONE**, and **no lingering AWS CLI process** remained. The governed profile was resolved by **static AST parse of the tracked `EXPECTED_PROFILE` constant** — the entry-point module was **neither imported nor executed** — and its value was **not disclosed**. A **minimal, allowlisted child environment was built key-by-key**: there was **no whole-environment copy**, and **no credential-bearing ambient variable was copied or inspected**. The **verification URL and the one-time device code appeared only transiently in the live AWS console**, and were **not repeated and not persisted**. Its underlying AWS network-request count is **UNKNOWN** |
| **one conditional identity confirmation**, because that login exited `0` | **exactly one** `aws sts get-caller-identity --no-cli-pager --output json` command, which **exited `0`**. The response **structurally contained non-empty `UserId`, `Account` and `Arn` fields**; the **raw response and the private identity values were neither displayed nor persisted**, the result was classified **`IDENTITY_CONFIRMED`**, and the captured buffers were **cleared after classification**. Identity was **confirmed at the time of that command** — a historical session fact that guarantees **no current or future session validity**. Its underlying AWS network-request count is **UNKNOWN**. It read no `KALPAMANI_SHARADAR_SECRET_ID`, **verified no secret, credential, bucket or provider access**, and is **not a fifth binding-preflight attempt** |
| **the fifth authorized attempt**, after PR #31 merged | **one** process invocation of the merged entry point, `AWS_PROFILE` pinned from a static AST parse of the tracked `EXPECTED_PROFILE` constant and never disclosed. It passed operator authorization, the governed profile contract, the AWS identity gate, licensed-bucket resolution and the secrets-boundary import, then made **one** secret-identifier resolution, **one** Secrets Manager client construction and **one** admitted `get_secret_value`, constructed **one** S3 client and **one** provider transport, and made **one** offline `preflight_qualification_composition` invocation that returned **`VALIDATED_OFFLINE`**. **Exit code `0`**; public output exactly `binding preflight completed` and `offline validation completed`; closed outcome **`COMPLETED + VALIDATION_COMPLETED`**. **S3 object operations ZERO · Sharadar/provider requests ZERO · qualification executions ZERO**, and its underlying AWS network-request count is **UNKNOWN** |
| **what the fifth attempt did not establish** | that the retrieved credential authenticates against Sharadar — **UNKNOWN**, because no provider request was made; that any particular number of AWS network requests left the machine — **UNKNOWN**; that the AWS session is valid now or later — **NOT GUARANTEED**. It is **not** authorization for a sixth attempt, for provider access, for an S3 object operation, or for an authenticated qualification run. The separately authorized authenticated attempt that later occurred is a **different surface** and did not change these facts |

**AWS identity-gate activity occurred, so total AWS activity was not zero.** What stayed at zero
**across the first four attempts** is narrower and is stated in scope: Secrets Manager client
constructions, `get_secret_value` invocations and Secrets Manager network requests; S3 object
operations; Sharadar and provider requests; S3 client constructions and provider transport
constructions. **None of the first four attempts reached composition validation, and none of them
retrieved or revealed a credential.** **The fifth attempt moved six of those counts to one** —
Secrets Manager client constructions, `get_secret_value` invocations, S3 client constructions,
provider transport constructions, offline composition-preflight invocations and credential
retrievals — and left **S3 object operations, Sharadar and provider requests, and qualification
executions at ZERO**. Its Secrets Manager **network**-request count is **UNKNOWN**, not one: an
admitted method invocation is not a proven request. **`reveal()` was still called zero times.**

**Whether the fourth attempt sent an AWS network request is UNKNOWN**, and this document does not
guess. The identity gate was invoked once and did not pass; a gate can fail before anything leaves
the machine, so neither zero nor one network request may be claimed.

**No standalone diagnosis was performed as part of attempt 4**, and what its governed identity
gate did internally is **UNKNOWN**. `identity_gate()` in `scripts/aws_foundation_verify.py` does
run `sts get-caller-identity` — but only after two checks that can refuse before it is reached:
an `AWS_PROFILE` that does not equal the governed constant, and an `expected_account()` that
returns `None` from a local, git-ignored `terraform.tfvars`, which is a plain file read. **A gate
invocation is therefore not proof of an STS command invocation**, and an earlier revision of this
section asserted one anyway.

**One of the two pre-STS conditions is proven for attempt 4, and the other is not.** The profile
condition holds mechanically: the binding preflight's own stage 2 compares `AWS_PROFILE` against a
constant whose literal value equals the verifier's, attempt 4 passed that stage in order to reach
the gate at stage 3, both reads happen in one process, and the module assigns nothing into
`os.environ` between them. The **account-binding condition is unproven**: the file
`expected_account()` reads is git-ignored, so no tracked history records its state; the gate's
reason string is consumed as pass/fail and is never printed or persisted; and nothing tracked
records which internal branch refused. Attempts 3 and 5 passed the gate on either side of
attempt 4, and bracketing is not evidence of that file's state at attempt 4 itself.

**So the fourth attempt's STS command invocation is UNKNOWN**, its underlying AWS network
interactions are **UNKNOWN**, and its identity-gate invocations are **ONE, which did not pass**.
What it did **not** do is run an *additional* diagnostic command or any SSO inspection, and no
authentication repair occurred during it. The gate's internal path is **not** the later
standalone diagnosis, which was a separate command run under its own authorization; **neither
that diagnosis nor the later successful refresh is retrospective proof of what attempt 4
reached**, and neither may be read backwards into it. The attempt's outcome is unchanged:
**`REFUSED_IDENTITY`**.

**A separately authorized diagnosis has since answered that. It is an additional standalone
command — neither the gate's own internal path above, nor the diagnosis that followed the first
attempt.** Run after the fourth attempt and after PR #28 merged, it
invoked **one** process and **one** `aws sts get-caller-identity` command, which exited **255** and
classified as **`REFUSED_SSO_SESSION_MISSING_OR_EXPIRED`** — the governed SSO session or cached
token was unavailable or expired. **It does not distinguish missing from expired**, and nothing
here guesses which. This is the **first direct diagnostic evidence explaining the fourth attempt's
identity refusal**, and it revises no count: the attempt's own network-request total stays
**UNKNOWN**, and so does the diagnosis command's, because a CLI call may resolve credentials
locally and fail before anything leaves the machine. **At that point SSO-login invocations were
ZERO**, **authentication-repair actions were ZERO** and **fifth binding-preflight attempts were
ZERO**; the first two of those have since moved — two SSO logins have now been attempted, and
the second refreshed the governed session — and the third has not — see the SSO-login
attempts below. Further AWS authentication diagnosis is **NOT AUTHORIZED**, and
**another AWS SSO refresh or login** is **NOT AUTHORIZED**.

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

**A separately authorized AWS SSO-login attempt has since been made, and it did not succeed.**
Run after the post-fourth diagnosis and after PR #29 merged, it invoked **one** process and
**one** `aws sso login --no-cli-pager` command. The governed profile was resolved by **statically
parsing the tracked `EXPECTED_PROFILE` constant** — the entry-point module was **neither imported
nor executed** — and pinned **in the child process only**, never disclosed. The current ambient
`AWS_PROFILE` value was **not deliberately inspected and not used as the profile selection**; the
profile came from that tracked constant.

**The child environment was built by copying the parent process environment, and that copy
transiently materialized the parent environment's values in the runner process** — the
credential-bearing ones included. That is a mechanical consequence of copying a process
environment, and it is stated rather than glossed: an earlier revision of this section asserted a
stronger absence than the mechanism supports.

**Copying is not inspection, use, disclosure or persistence, and those are what the boundary is
about.** The named ambient static AWS credential variables were **removed from the child
environment before the AWS CLI process was started** — by name, so their presence or values were
**not individually inspected, tested, enumerated or classified**. They were **not passed to, and
not used by, the AWS CLI child**. **No credential value was printed, logged, disclosed or
persisted**, and **the parent environment itself was not modified**. The removal exists so
unrelated credentials held on this workstation for another project could not override the governed
profile, which is the §4.24 wrong-account hazard in its AWS form.

**It timed out after 420 seconds**, was terminated, and left **no lingering AWS CLI process**. A
terminated process returns no status, so this is recorded as **exit code: NOT AVAILABLE / PROCESS
TERMINATED ON TIMEOUT** — never as a numeric exit code — and the closed public outcome is
**`REFUSED_SSO_LOGIN`**. **Browser authorization interactions ZERO · device authorizations
completed ZERO · successful SSO refreshes ZERO · identity-confirmation command invocations ZERO ·
fifth binding-preflight attempts ZERO.** Its underlying AWS network-request count is **UNKNOWN**,
for the reason every count here is: a CLI invocation is not one network request, and a call may
resolve locally and fail before anything leaves the machine.

**The SSO session remained unrefreshed**, and the earlier diagnosis stands unrevised at
**`REFUSED_SSO_SESSION_MISSING_OR_EXPIRED`**. This attempt produced **no evidence distinguishing
missing from expired**, **did not verify or contradict the owner-configured secret identifier**,
and **retrieved no credential**. Every Secrets Manager, S3, provider and qualification zero
recorded above is unchanged by it.

**The likely cause is procedural, and it is recorded as likely rather than proven.** The evidence
is what the operator's own handling produced: stdout and stderr were **captured rather than
streamed**, no browser appeared, no device URL or code was displayed to the owner, and the process
waited the full 420 seconds. The supportable conclusion is that **the failed interaction was
likely caused by suppressing the interactive browser/device-code surface**. That is an
**operational-handling explanation, not proof of an AWS configuration defect**. Whether the AWS
CLI emitted a device URL or code into the undisplayed buffer **was not inspected and remains
UNKNOWN**, and **no raw output may be inspected now to resolve that uncertainty**. Nothing here
establishes a defective AWS SSO configuration, an incorrect governed profile, a wrong SSO
start URL, any particular technical reason for a browser not appearing, or the presence or
absence of a generated device code.

**A failed login attempt is not permission to retry.** **Another AWS SSO-login/refresh attempt
NOT AUTHORIZED · further AWS authentication diagnosis NOT AUTHORIZED · a sixth binding-preflight
attempt NOT AUTHORIZED · additional credential or Secrets Manager access NOT AUTHORIZED ·
a third authenticated qualification attempt NOT AUTHORIZED.**

**A corrected, separately authorized SSO login has since completed, and the governed session was
refreshed.** Run in a new Claude session after PR #30 merged, it invoked **one** process and
**one** `aws sso login --no-cli-pager` command — this time on a **live console with inherited
stdin, stdout and stderr**. Nothing was captured, piped, redirected, buffered or written to a
file. The **interactive browser/device flow completed**, the command **exited `0`**, **no
lingering AWS CLI process remained**, and **successful governed SSO refreshes became ONE**.

**Output handling was one deliberate correction, and the evidence stops short of a cause.** The
first attempt captured stdout and stderr; the corrected attempt used a live console with inherited
stdin, stdout and stderr, and it completed successfully. **Streaming the interactive surface was a
deliberate corrective measure**, chosen because a browser/device flow has to be able to reach the
person completing it. That sequence is **consistent with the interactive surface contributing to
the earlier timeout**, and it establishes nothing further: the earlier buffer was never inspected,
and **capture is not established as the sole, necessary, sufficient or definitive cause**. The
earlier finding stands exactly where it was recorded — **likely, not proven**.

**The two attempts differed in more than output handling, which is why no cause is claimed.** They
ran in different Claude sessions; the first copied the whole parent process environment while the
corrected one built a minimal allowlisted child environment key-by-key; and the point-in-time SSO
state may itself have differed. **Nothing here claims the two runs were otherwise identical**, and
**the second attempt's success does not establish why the first failed**.

**The child environment was built the narrow way this time.** The governed profile was resolved by
**static AST parse of the tracked `EXPECTED_PROFILE` constant** — the entry-point module was
**neither imported nor executed** — and the value was **not disclosed**. A **minimal,
allowlisted child environment was built key-by-key**: there was **no whole-environment copy**, and
**no credential-bearing ambient variable was copied or inspected**. That closes the transient
materialization the first attempt's whole-environment copy produced, and it is stated as a
property of **this** run rather than backdated onto the earlier one, which is recorded above
exactly as it happened. The **verification URL and the one-time device code appeared only
transiently in the live AWS console**, and were **not repeated and not persisted** — not here,
not in a log, and not in any file.

**Because that login exited `0`, exactly one identity confirmation ran.** One
`aws sts get-caller-identity --no-cli-pager --output json` command, which **exited `0`**. The
response **structurally contained non-empty `UserId`, `Account` and `Arn` fields**, and that
structural check is the whole of what was read from it. The **raw response and the private
identity values were neither displayed nor persisted**, the outcome was classified
**`IDENTITY_CONFIRMED`**, and the **captured buffers were cleared after classification**. Its
underlying AWS network-request count is **UNKNOWN**, for the reason every count here is.

**A successful identity confirmation is a historical session fact and nothing more.** Identity was
**confirmed at the time of that command**; **no current or future session validity is guaranteed**
by it, because a session can expire between one command and the next. It **verified no secret
identifier, no secret, no API key, no bucket and no provider access** — it did not read
`KALPAMANI_SHARADAR_SECRET_ID`, construct a Secrets Manager or S3 client, invoke
`get_secret_value`, retrieve a credential or bind a bucket. It is **not** a fifth binding-preflight
attempt: **the fifth attempt came later, under its own separate authorization, and is recorded
below.**

**A completed authorization is not a standing one.** Two SSO-login attempts have now been
separately authorized — the first refused, the second succeeded — and each was authorized
for itself, not for the next one. **The same holds for the five binding-preflight attempts, the
fifth and successful one included.** **Another AWS SSO refresh or login is SEPARATELY GATED and NOT
AUTHORIZED · further AWS authentication diagnosis NOT AUTHORIZED · a sixth
binding-preflight attempt NOT AUTHORIZED · additional credential or Secrets Manager access NOT
AUTHORIZED · an authenticated qualification run NOT AUTHORIZED.**

**`KALPAMANI_SHARADAR_SECRET_ID` is now OWNER-CONFIGURED AND RESOLVED ONCE BY THE ENTRY
POINT.** It was **UNKNOWN at the time of the second attempt**, which refused on the
dependency path without reading it — and ADR-0016 exists
because that refusal was reported as a credential failure, which is what made the two
indistinguishable. It was **still UNKNOWN at the time of the third attempt**, which resolved the
fixed source exactly once and refused with `REFUSED_SECRET_IDENTIFIER` because no usable identifier
came back. **The owner created the secret and configured the variable only after the third
attempt**, so none of the first three could have seen it — and the **fourth attempt refused at
the AWS identity gate, two stages before the identifier source**, so it did not read the variable
either. **The fifth attempt resolved it exactly once**, and the identifier was admitted by the
identifier grammar, used to construct one Secrets Manager client, and never disclosed.

**What entry-point resolution did and did not establish.** It establishes that the variable was
inherited by the invoking process, that the entry point resolved it once, that the value satisfied
the identifier grammar, and that `get_secret_value` against it returned a `SecretString` the
existing credential contract **accepted structurally**. It establishes **nothing about Sharadar**:
the payload's suitability as a provider API key is **UNKNOWN**, because **no provider request was
made**. The identifier, the secret name, any ARN and the credential itself were **not inspected,
displayed, logged, hashed, fingerprinted, measured, summarized or persisted** by this repository or
by any session. **Additional credential or Secrets Manager access remains NOT AUTHORIZED**, and so
do a sixth binding-preflight attempt, any **further** AWS authentication diagnosis, and **another**
AWS SSO refresh or login. **The corrected SSO refresh and the identity confirmation still changed
none of that**: neither read `KALPAMANI_SHARADAR_SECRET_ID`, and **neither verified the secret, the
credential, the bucket or provider access** — the fifth attempt, later and separately authorized,
is what read it.

**A real binding preflight is no longer a future event at all.** Five preflight attempts have
occurred — **four refused and the fifth completed** — and **two** SSO-login attempts have been
separately authorized, the first timing out and the second succeeding, with **one sanitized
identity confirmation** after it. What remains future, and separately authorized: a **sixth**
attempt, **further** AWS authentication diagnosis, **another** AWS SSO refresh or login, further
environment resynchronization, **additional** credential or Secrets Manager access, further
provider access, any further S3 object operation, and a **third** authenticated Sharadar
qualification attempt.
**Two authenticated qualification attempts have since occurred, each separately authorized.**
The first **refused at the AWS identity gate with `REFUSED_IDENTITY` and exit code `6`** — it
retrieved no credential and made no provider request. The second **COMPLETED with exit code
`0`**, reached the qualification runtime and **made one provider request**, with its **S3
qualification operations bounded at THREE TO SIX**. **Neither was a sixth binding-preflight
attempt, and a third attempt is NOT AUTHORIZED.**

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
exactly one may call the composition, the credential source refuses by default, and all of it has
been run exactly once — by the fifth separately authorized attempt, offline.** Each clause is a
test, and the existing dormancy guards were narrowed rather than removed. **The structural
guarantees are unchanged by that run**: no second construction site exists, no second caller of the
composition exists, and the default path still refuses.

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
real credential binding: NONE   ·   real bucket binding: NONE -- in this module
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

**A further authenticated qualification run remains separately gated, and this slice does not
approach it.** What would still be needed: an authorization, a credential source, a real credential,
a constructed **AWS SDK** client, a resolved licensed bucket, and code that calls something other
than `preflight_qualification_composition`. **The fifth separately authorized binding-preflight
attempt supplied the first five, once and offline** — under its own authorization, in the operator
entry point, not in this module. **The sixth was supplied elsewhere**: nothing in *this* module calls anything other than
`preflight_qualification_composition`, so this module has caused no qualification execution,
provider request or S3 object operation. The authenticated surface added by
[ADR-0017](docs/decisions/ADR-0017-bounded-authenticated-sharadar-acquisition-qualification.md)
is a different, separately authorized path; it has been attempted twice — refused, then
COMPLETED — and a **third** run stays a separate, unauthorized decision.

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
SDK client construction: that entry point ONLY -- ONE S3 client and ONE Secrets Manager
                         client, on the fifth authorized attempt
licensed-bucket resolutions: ONE   ·   S3 object operations: ZERO
runner: NONE   ·   module entry point in either module: NONE
constructed by the composition root (ADR-0014, extended by ADR-0017) and its own tests
Sharadar requests sent by these modules themselves: ZERO   ·   AWS requests sent: ZERO
reached through the ADR-0017 authenticated entry point: TWICE -- REFUSED, then COMPLETED
```

That claim once ended *"and no composition root exists"*.
[ADR-0014](docs/decisions/ADR-0014-implement-the-dormant-sharadar-qualification-composition-root.md)
built one, so the accurate statement is narrower: a dormant composition root constructs this runtime
from injected values and exposes **offline preflight only**. What still stands between it and a live
run is a separately gated authorization plus the real private bindings — a credential source, a
constructed SDK client, a resolved bucket — and code that calls something other than `preflight`.
**The fifth authorized binding-preflight attempt supplied the first three, once and offline**: a
credential was retrieved and structurally accepted, an S3 client was constructed, and the governed
licensed bucket was resolved. **The fourth was supplied elsewhere**: nothing on *this* dormant path calls anything other
than `preflight`, so this path has caused no qualification execution, provider request or S3
object operation. The separately authorized ADR-0017 surface has been attempted twice —
refused, then COMPLETED — and a **third** authenticated qualification run remains a separate,
unauthorized decision.

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
               ADR-0014 dormant composition root + offline preflight -- ACCEPTED /
                        IN FORCE -- PR #19 MERGED, CODE ONLY, OFFLINE PREFLIGHT ONLY,
                        NO QUALIFICATION-RUN EXECUTION SURFACE, NEVER RUN
               ADR-0015 dormant private-binding preflight -- ACCEPTED / IN FORCE --
                        PR #22 MERGED, CODE ONLY, REFUSED BY DEFAULT, BINDING
                        PREFLIGHT ONLY; FIVE SEPARATELY AUTHORIZED ATTEMPTS,
                        THE FIRST FOUR REFUSED, THE THIRD WITH
                        REFUSED_SECRET_IDENTIFIER AT THE SECRET-IDENTIFIER
                        SOURCE AND THE FOURTH WITH REFUSED_IDENTITY AT THE AWS
                        IDENTITY GATE; SECRET IDENTIFIER OWNER-CONFIGURED, SET
                        UP AFTER THE THIRD ATTEMPT, NOT READ BY THE FOURTH,
                        WHICH REACHED NEITHER BUCKET NOR IDENTIFIER RESOLUTION,
                        AND RESOLVED ONCE BY THE ENTRY POINT ON THE FIFTH; AWS
                        IDENTITY-GATE ACTIVITY OCCURRED, FOURTH-ATTEMPT AWS
                        NETWORK REQUESTS UNKNOWN; ACROSS THE FIRST FOUR ATTEMPTS
                        NO SECRETS MANAGER CLIENT, CREDENTIAL, S3 OBJECT
                        OPERATION, SHARADAR REQUEST OR QUALIFICATION RUN;
                        POST-FOURTH AWS
                        IDENTITY DIAGNOSIS COMPLETED --
                        REFUSED_SSO_SESSION_MISSING_OR_EXPIRED, ONE COMMAND, EXIT
                        CODE 255, MISSING AND EXPIRED NOT DISTINGUISHED, ITS OWN
                        NETWORK COUNT UNKNOWN, ZERO SSO LOGINS DURING IT, ZERO
                        REPAIR ACTIONS DURING IT; POST-DIAGNOSIS AWS SSO-LOGIN
                        ATTEMPT COMPLETED -- REFUSED_SSO_LOGIN, ONE COMMAND,
                        TIMED OUT AFTER 420 SECONDS, NO EXIT STATUS RETURNED,
                        NO LINGERING AWS CLI PROCESS, ZERO BROWSER
                        AUTHORIZATIONS, ZERO DEVICE AUTHORIZATIONS, ZERO
                        SUCCESSFUL REFRESHES, ZERO IDENTITY CONFIRMATIONS, ITS
                        OWN NETWORK COUNT UNKNOWN, SSO SESSION STILL
                        UNREFRESHED AFTER IT, EARLIER DIAGNOSIS UNREVISED,
                        LIKELY CAUSE INTERACTIVE-SURFACE SUPPRESSION --
                        LIKELY, NOT PROVEN; CORRECTED SECOND AWS SSO-LOGIN
                        ATTEMPT COMPLETED SUCCESSFULLY -- ONE COMMAND IN A
                        NEW CLAUDE SESSION, LIVE CONSOLE WITH INHERITED STDIN,
                        STDOUT AND STDERR, NO CAPTURED, PIPED, REDIRECTED,
                        BUFFERED OR FILE OUTPUT, INTERACTIVE
                        BROWSER/DEVICE FLOW COMPLETED, EXIT CODE 0, NO
                        LINGERING AWS CLI PROCESS, SUCCESSFUL GOVERNED SSO
                        REFRESHES ONE, MINIMAL ALLOWLISTED CHILD ENVIRONMENT
                        BUILT KEY-BY-KEY, NO WHOLE-ENVIRONMENT COPY, NO
                        CREDENTIAL-BEARING AMBIENT VARIABLE COPIED OR
                        INSPECTED, GOVERNED PROFILE FROM A STATIC AST PARSE
                        OF EXPECTED_PROFILE AND NEVER DISCLOSED,
                        VERIFICATION URL AND ONE-TIME DEVICE CODE TRANSIENT
                        IN THE LIVE CONSOLE ONLY, ITS OWN NETWORK COUNT
                        UNKNOWN; ONE SANITIZED IDENTITY CONFIRMATION
                        FOLLOWED IT -- AWS STS GET-CALLER-IDENTITY, EXIT
                        CODE 0, NON-EMPTY USERID, ACCOUNT AND ARN
                        STRUCTURALLY PRESENT, RAW RESPONSE AND PRIVATE
                        IDENTITY VALUES NEITHER DISPLAYED NOR PERSISTED,
                        CLASSIFIED IDENTITY_CONFIRMED, CAPTURED BUFFERS
                        CLEARED AFTER CLASSIFICATION, ITS OWN NETWORK COUNT
                        UNKNOWN, IDENTITY CONFIRMED AT THE TIME OF THAT
                        COMMAND WITH NO GUARANTEE OF CURRENT OR FUTURE
                        SESSION VALIDITY, AND VERIFYING NO SECRET
                        IDENTIFIER, SECRET, CREDENTIAL, BUCKET OR PROVIDER
                        ACCESS; FIFTH BINDING-PREFLIGHT ATTEMPTS ZERO AT
                        THAT POINT; THE FIFTH SEPARATELY AUTHORIZED ATTEMPT
                        THEN RAN EXACTLY ONCE AND COMPLETED -- EXIT CODE 0,
                        PUBLIC OUTPUT EXACTLY "binding preflight completed"
                        AND "offline validation completed", CLOSED OUTCOME
                        COMPLETED + VALIDATION_COMPLETED, LAST STAGE
                        DEFINITIVELY REACHED STAGE 10 WITH ONE
                        preflight_qualification_composition INVOCATION
                        RETURNING VALIDATED_OFFLINE; IDENTITY-GATE
                        INVOCATIONS ONE AND PASSED, LICENSED-BUCKET
                        RESOLUTIONS ONE, SECRET-IDENTIFIER RESOLUTIONS ONE,
                        SECRETS MANAGER CLIENT CONSTRUCTIONS ONE,
                        GET_SECRET_VALUE INVOCATIONS ONE AND ADMITTED, S3
                        CLIENT CONSTRUCTIONS ONE, S3 OBJECT OPERATIONS ZERO,
                        PROVIDER TRANSPORT CONSTRUCTIONS ONE,
                        SHARADAR/PROVIDER REQUESTS ZERO, OFFLINE
                        COMPOSITION-PREFLIGHT INVOCATIONS ONE, QUALIFICATION
                        EXECUTIONS ZERO, UNDERLYING AWS NETWORK REQUESTS
                        UNKNOWN; ONE CREDENTIAL RETRIEVED AND STRUCTURALLY
                        ACCEPTED, PASSED INTO THE OFFLINE COMPOSITION AND
                        NEVER DISPLAYED, LOGGED, PERSISTED, HASHED,
                        FINGERPRINTED, MEASURED OR SUMMARIZED, WITH SHARADAR
                        AUTHENTICATION UNKNOWN AND NO PROVIDER REQUEST MADE;
                        A SIXTH ATTEMPT, FURTHER AWS AUTHENTICATION
                        DIAGNOSIS, ANOTHER SSO-LOGIN/REFRESH ATTEMPT AND
                        ADDITIONAL CREDENTIAL OR SECRETS MANAGER ACCESS
                        SEPARATELY GATED AND NOT AUTHORIZED
               ADR-0016 corrected private-binding failure boundaries -- ACCEPTED /
                        IN FORCE -- PR #24 MERGED, CODE AND FAILURE-BOUNDARY
                        CORRECTION ONLY, SECRET-IDENTIFIER / LOCAL-DEPENDENCY /
                        CREDENTIAL REFUSALS SEPARATED, FURTHER ENVIRONMENT
                        RESYNCHRONIZATION SEPARATELY GATED, A SIXTH BINDING-PREFLIGHT
                        ATTEMPT NOT AUTHORIZED; FIRST EXERCISED PAST THE
                        IDENTIFIER STAGE BY THE FIFTH ATTEMPT, WHICH RETRIEVED
                        ONE STRUCTURALLY ACCEPTED CREDENTIAL AND RAN NO
                        QUALIFICATION
               ADR-0017 bounded authenticated acquisition qualification -- ACCEPTED /
                        IN FORCE -- PR #33 MERGED, MERGE COMMIT
                        4fab37cd9468bc48b62a80e49e5a17a203870926, APPROVED ADR HEAD
                        679863fd7f540f47ae4f47aee8d5e363d72caffd. THE MERGE
                        ACCEPTANCE CONDITION HAS OCCURRED, SO IT IS NO LONGER
                        PROPOSED; IT CARRIED NO AUTHORITY WHILE PR #33 WAS OPEN,
                        WHICH WAS TRUE THEN AND IS NOT REWRITTEN. THE
                        AUTHENTICATED ACQUISITION ENTRY POINT IS NOW IMPLEMENTED,
                        ATTEMPTED TWICE -- REFUSED, THEN COMPLETED.
                        AUTHENTICATED ENTRY POINTS
                        IMPLEMENTED ONE; scripts/sharadar_authenticated_qualification.py
                        REFUSES BY DEFAULT; THE ACCEPTED COMPOSITION ROOT WAS
                        EXTENDED, NOT DUPLICATED, AND
                        QualificationRuntime.execute NOW HAS EXACTLY ONE
                        ADR-0017 PRODUCTION CALLER, AND THE REPOSITORY NOW HAS
                        EXACTLY TWO PRODUCTION CALL SITES OVERALL -- THAT
                        UNCHANGED ADR-0017 COMPOSITION, AND THE SEPARATE
                        DORMANT ADR-0018 / ADR-0019 / ADR-0020 QUALIFICATION
                        ACQUISITION PATH MERGED BY PR #48, WHICH DOES NOT
                        ALTER, BROADEN OR BECOME REACHABLE FROM ADR-0017.
                        IMPLEMENTING IT WAS NOT PERMISSION TO
                        USE IT, ONE REFUSED ATTEMPT IS NOT PERMISSION FOR A
                        SECOND, AND ONE COMPLETED ATTEMPT IS NOT PERMISSION FOR
                        A THIRD: A THIRD EXECUTION OF THE SURFACE REMAINS
                        SEPARATELY GATED AND NOT AUTHORIZED, AND IMPLEMENTATION,
                        EXECUTION AND EMPIRICAL QUALIFICATION REMAIN THREE
                        DISTINCT GATES. TWO SEPARATELY AUTHORIZED EXECUTIONS
                        WERE ATTEMPTED IN FRESH SESSIONS -- THE FIRST REFUSED
                        AND THE SECOND COMPLETED. AUTHENTICATED QUALIFICATION
                        ATTEMPTS TWO -- ONE REFUSED, ONE COMPLETED;
                        ENTRY-POINT PROCESS INVOCATIONS TWO, EXACTLY ONE PER
                        ATTEMPT. ATTEMPT ONE -- CLOSED OUTCOME
                        REFUSED_IDENTITY; EXIT CODE 6; LAST STAGE DEFINITIVELY
                        REACHED STAGE 5, THE AWS IDENTITY GATE; STAGES 1-4
                        PASSED; PUBLIC OUTPUT EXACTLY "authenticated
                        qualification refused: the AWS identity gate did not
                        pass"; AWS IDENTITY-GATE INVOCATIONS ONE, REFUSED;
                        LICENSED-BUCKET RESOLUTIONS ZERO; TERRAFORM COMMAND
                        INVOCATIONS ZERO; SECRET-IDENTIFIER RESOLUTIONS ZERO;
                        KALPAMANI_SHARADAR_SECRET_ID READS ZERO; SECRETS MANAGER
                        CLIENT CONSTRUCTIONS ZERO; GET_SECRET_VALUE INVOCATIONS
                        ZERO; CREDENTIAL RETRIEVALS BY THIS ATTEMPT ZERO; S3
                        CLIENT CONSTRUCTIONS ZERO; PROVIDER TRANSPORT
                        CONSTRUCTIONS ZERO;
                        QUALIFICATION-RUNTIME EXECUTIONS AGAINST REAL SERVICES
                        ZERO; APPLICATION-LEVEL PROVIDER FETCHES ZERO;
                        SHARADAR/PROVIDER REQUESTS ZERO; PUTOBJECT ZERO;
                        CONDITIONAL HEADOBJECT ZERO; S3 OBJECT-BYTE READS ZERO;
                        S3 QUALIFICATION OPERATIONS ZERO; CONTROL OPERATIONS
                        ZERO; .runtime/ WRITES FROM THIS ATTEMPT ZERO;
                        UNDERLYING AWS/NETWORK INTERACTIONS UNKNOWN; THE GATE'S
                        OWN STS COMMAND INVOCATION UNKNOWN, BECAUSE REAL
                        PRE-STS REFUSAL PATHS EXIST; THE CAUSE OF THE REFUSAL
                        UNDIAGNOSED AND NOT INFERRED -- NOT A MISSING SSO
                        SESSION, NOT AN EXPIRED ONE, NOT A CREDENTIAL DEFECT
                        AND NOT A PROVIDER FAILURE; NO RETRY, DIAGNOSIS, SSO
                        LOGIN OR REPAIR FOLLOWED IT. ATTEMPT TWO --
                        ENTRY-POINT PROCESS INVOCATIONS ONE; EXIT CODE 0;
                        CLOSED RESULT OBSERVED YES; CLOSED RESULT COMPLETED;
                        QUALIFICATION RUNTIME REACHED YES;
                        QUALIFICATION-RUNTIME EXECUTIONS ONE; PROVIDER REQUESTS
                        ONE; PUTOBJECT INVOCATIONS EXACTLY THREE; CONDITIONAL
                        HEADOBJECT INVOCATIONS ZERO TO THREE; S3 QUALIFICATION
                        OPERATIONS THREE TO SIX; PUBLICATION STATE UNKNOWN NO;
                        COMPLETE ACQUISITION RECORD EXISTS; NEWLY WRITTEN
                        OBJECTS NOT ESTABLISHED; ALREADY-PRESENT IDENTICAL
                        OBJECTS NOT ESTABLISHED; UNDERLYING
                        AWS/NETWORK INTERACTIONS UNKNOWN. COMPLETED IS A
                        COMMAND STATUS, NOT A VERDICT -- NOT QUALIFICATION
                        PASSED, NOT THE PROVIDER ACCEPTED, NOT A PROVIDER
                        SELECTED, NOT A CLOSURE OF G1 OR G2, NOT A COMPLETION
                        OF PHASE 3,
                        AND NOT PRODUCTION, CONTROL OR LIVE-TRADING READINESS.
                        CUMULATIVELY -- QUALIFICATION-RUNTIME EXECUTIONS ONE;
                        KNOWN PROVIDER REQUESTS ONE; S3 QUALIFICATION
                        OPERATIONS THREE TO SIX, ATTEMPT ONE ZERO AND
                        ATTEMPT TWO THREE TO SIX; EXACT-REQUEST AUTHENTICATION
                        ESTABLISHED; PROVIDER-WIDE AUTHENTICATION UNKNOWN;
                        SUBSCRIPTION-WIDE ENTITLEMENT UNKNOWN; P1-P9 EXECUTIONS
                        ZERO; INGESTION AND TRADING OPERATIONS ZERO. NEITHER
                        WAS A SIXTH BINDING-PREFLIGHT ATTEMPT AND
                        BINDING-PREFLIGHT ATTEMPTS REMAIN FIVE. CREDENTIAL
                        RETRIEVALS ESTABLISHED BY COUNT ONE FROM BINDING
                        ATTEMPT 5, WITH ATTEMPT TWO'S COUNT NOT ESTABLISHED.
                        PRESERVES ONE
                        REQUEST = ONE DURABLE ACQUISITION, THE OPAQUE-PAYLOAD
                        BOUNDARY WITH NO PARSER INTRODUCED,
                        AcquisitionMode.QUALIFICATION WITH NO FOURTH MODE, ONE
                        PROVIDER REQUEST, NO PAGINATION, NO AUTOMATIC RETRY, THE
                        SEVEN-DAY TRAILING WINDOW, LICENSED BRONZE PUBLICATION OF
                        THREE DURABLE ARTIFACTS IN EXACTLY THREE PUTOBJECT
                        OPERATIONS WITH ZERO TO THREE CONDITIONAL HEADOBJECT
                        METADATA CHECKS ONLY AFTER 412, ZERO OBJECT-BYTE READS,
                        ZERO .runtime/ WRITES AND NO EXTRA QUALIFICATION REPORT.
                        FULL P1-P9 EMPIRICAL QUALIFICATION SEPARATE AND
                        UNEXECUTED, NO PROVIDER SELECTED, G1 OPEN, G2 OPEN
               ADR-0018 bounded private empirical Sharadar qualification --
                        ACCEPTED / IN FORCE -- PR #39 MERGED, MERGE COMMIT
                        97e7ce57bb90303c78c2a1a4bc3ac2301b60f694, APPROVED ADR
                        HEAD 25ee0b0a6ab17c1fea7e2fa4ccd72ce8b2864780. THE
                        CONDITIONAL ACCEPTANCE EVENT HAS OCCURRED, SO IT IS NO
                        LONGER PROPOSED. WHILE PR #39 WAS OPEN IT WAS PROPOSED
                        AND CARRIED NO AUTHORITY, WHICH WAS TRUE THEN AND IS NOT
                        REWRITTEN. THE MERGE APPROVED ARCHITECTURE ONLY -- THE
                        EVIDENCE INVENTORY, THE P1-P9 CEILINGS, THE TWO-PROCESS
                        SPLIT, THE DETERMINISTIC PRIVATE LOCATOR, THE OPERATION
                        ARITHMETIC, THE TWO LEAST-PRIVILEGE ROLES, THE
                        PARSER/EVALUATOR/REPORT BOUNDARIES AND THE
                        DELETION-RUNBOOK CLARIFICATION. THE MERGE AUTHORIZED NO
                        IMPLEMENTATION, NO INFRASTRUCTURE MUTATION AND NO
                        EXECUTION. IT SUPERSEDES NOTHING AND REWRITES NEITHER
                        ADR-0011 NOR ADR-0017 -- ADR-0011'S NO-READ-SURFACE
                        STATEMENT STAYS TRUE OF THE STORE IT AUTHORIZED, AND
                        ADR-0017'S EXACTLY-THREE-PUTOBJECT ACCOUNTING IS
                        UNTOUCHED. DESIGNED, NOT BUILT -- EIGHT PRIVATE SUBJECT
                        CLASSES NEVER RECORDED AS NAMES, DATASETS TICKERS,
                        STOCKS AND ACTIONS ONLY, 48 REQUESTS PER RUN, ZERO
                        PROVIDER RETRIES, TWO RUNS AT LEAST EIGHT CALENDAR DAYS
                        APART, 96 PROVIDER REQUESTS MAXIMUM ACROSS BOTH,
                        MAXIMUM PUTOBJECT 147 AND MAXIMUM CONDITIONAL
                        HEADOBJECT 145 PER RUN, MAXIMUM 292 S3 OPERATIONS PER
                        RUN AND 584 ACROSS TWO, ONE COMBINED RUN A / RUN B
                        ASSESSMENT AFTER RUN B WITH 194 GETOBJECT AND 195-196
                        TOTAL, TWO SEPARATE ROLES AND SESSIONS, AND NO S3
                        LISTING ANYWHERE. THE CLARIFICATION AMENDMENT IS
                        EFFECTIVE -- PR #42 MERGED, MERGE COMMIT
                        28239514b9e4e13f55ee98fa50877077e70bd593, APPROVED
                        CLARIFICATION HEAD
                        579259a62ff7561ae2991f3923ea8aa1d0064be8. THE
                        CONDITIONAL EFFECTIVENESS EVENT HAS OCCURRED, SO
                        ADR-0018'S TOTAL ELAPSED ACQUISITION DEADLINE
                        CLARIFICATION IS NOW EFFECTIVE AND ADR-0018'S COMBINED
                        RUN A / RUN B ASSESSMENT CLARIFICATION IS NOW
                        EFFECTIVE, RECORDING THE 1,800-SECOND ACQUISITION
                        ELAPSED-TIME DEADLINE ON AN INJECTED MONOTONIC CLOCK
                        AND SUPERSEDING THE CANONICAL ONE-LOCATOR ARITHMETIC
                        OF 97 GETOBJECT AND 98-99 OPERATIONS. WHILE PR #42 WAS
                        OPEN THE CLARIFICATION WAS PROPOSED AND CARRIED NO
                        AUTHORITY. THE MERGE APPROVED CLARIFICATION OF
                        ARCHITECTURE ONLY, AND THE CLARIFICATION MERGE
                        AUTHORIZED NO IMPLEMENTATION, NO INFRASTRUCTURE
                        MUTATION AND NO EXECUTION. THE OFFLINE IMPLEMENTATION
                        IS MERGED AND DORMANT -- PR #41 MERGED, MERGE COMMIT
                        3ddd7d40741bb9a50ae4fc5452324ddbfb5e1ec0, APPROVED
                        IMPLEMENTATION HEAD
                        96daac7963d936f231b37847579c5f28bb313760 -- AND THE
                        FIXED 48-REQUEST ASSESSMENT-BOUNDARY CORRECTION IS
                        MERGED -- PR #44 MERGED, MERGE COMMIT
                        c945970613b80bfd4f42acc4f3acb4814895eb42, APPROVED
                        CORRECTION HEAD
                        78b4425077e65eeb12dfd24b35825741370e0e0f. THE OFFLINE
                        IMPLEMENTATION WAS CORRECTED AGAINST THE
                        NOW-AUTHORITATIVE CLARIFICATION UNDER A SEPARATELY
                        AUTHORIZED IMPLEMENTATION CORRECTION, AND THE
                        INDEPENDENT RE-REVIEW HAS SINCE OCCURRED AND PRODUCED
                        THE FIXED-COUNT CORRECTION MERGED AS PR #44. MERGING AN
                        IMPLEMENTATION AUTHORIZED NO EXECUTION, NO
                        INFRASTRUCTURE DEPLOYMENT AND NO RUN. A SANITIZED RUNTIME-AREA LISTING INCIDENT IS
                        RECORDED -- FILENAMES OBSERVED, NO FILE CONTENTS READ,
                        NOT REPRODUCED BY THE REVIEW, NO TRACKED CONTAMINATION
                        FOUND, FILENAMES INTENTIONALLY NOT DISCLOSED, AND IT
                        AUTHORIZES NEITHER PRIVATE-DIRECTORY INSPECTION NOR
                        FURTHER DIAGNOSIS. EMPIRICAL-PACKAGE EXECUTIONS ZERO,
                        PROVIDER REQUESTS BY THIS PACKAGE ZERO, S3 OPERATIONS BY
                        THIS PACKAGE ZERO, P1-P9 EXECUTIONS BY THIS PACKAGE
                        ZERO, LOCATORS ZERO, PRIVATE REPORTS ZERO, NEW IAM ROLES
                        ZERO, AND THE LICENSED OBJECT-BYTE READ SURFACE IS
                        MERGED, DORMANT AND NOT DEPLOYED -- THE BOUNDED
                        ASSESSMENT-ONLY READ IMPLEMENTATION NOW EXISTS IN
                        COMMITTED CODE, IT PERMITS NO S3 LISTING, IT IS NOT A
                        GENERAL READ SURFACE, AND IT HAS NEVER BEEN EXECUTED
                        AGAINST LICENSED OBJECTS. ADR-0018 IMPLEMENTATION
                        EXECUTION NOT AUTHORIZED,
                        INFRASTRUCTURE MUTATION NOT AUTHORIZED, RUN A NOT
                        AUTHORIZED, RUN B NOT AUTHORIZED, ASSESSMENT NOT
                        AUTHORIZED -- IMPLEMENTATION, INFRASTRUCTURE MUTATION
                        AND EXECUTION STAY THREE SEPARATE GATES AND ARE NEVER
                        COLLAPSED INTO ONE. NO PROVIDER SELECTED, G1 OPEN,
                        G2 OPEN
NOT AUTHORIZED additional application credential retrieval -- one occurred, on the
                        fifth separately authorized attempt, and is recorded above
               additional Secrets Manager client construction or use, except during a
                        separately authorized ADR-0015 binding-preflight attempt
               licensed-bucket resolutions ONE · S3 client constructions ONE ·
                        S3 object operations ZERO -- "real bucket binding" is
                        undefined in this repository and is stated as those facts
               SDK/client construction outside the ADR-0015 operator boundary, which
                        has constructed one Secrets Manager client, one S3 client and
                        one provider transport, all on the fifth attempt
               a qualification-run execution surface on the composition root
               a second composition root
               ANY provider API call · the published test token · Services Data · bulk download
               empirical qualification · production backfill · production ingestion
               Silver/Gold real data · production-provider SELECTION
               ANY FURTHER AWS mutation, read, verifier run or terraform command ·
                        ECR/ECS · image builds
               ANY S3 object operation or publication · ANY Sharadar/provider access
               an ingestion runner · a THIRD authenticated qualification attempt ·
                        CONTROL publication -- two authenticated attempts occurred, the
                        first refusing at the AWS identity gate and the second
                        completing, and neither authorizes any other
               further dependency installation or environment resynchronization --
                        separately gated; the declared range stays as declared and no
                        manifest or lock is changed
               a sixth binding-preflight attempt -- five have occurred, the first four
                        refused and the fifth completed; neither correcting what a
                        refusal says, nor configuring a secret, nor completing an
                        attempt is permission to produce another one
               further AWS authentication diagnosis -- one completed after the fourth
                        attempt and is recorded; a refusal at the identity gate is a
                        completed diagnostic result, not permission to repair and try
                        again, and neither is a completed diagnosis
               another AWS SSO refresh or login -- separately gated; two authorized
                        attempts have occurred, the first timing out and the second
                        completing successfully, and a completed authorization is not
                        a standing one, any more than a failed login was permission to
                        retry or classifying a session was permission to replace it
               a THIRD execution of the bounded authenticated acquisition
                        qualification -- ADR-0017 is ACCEPTED / IN FORCE; two
                        separately authorized executions have occurred -- the first
                        REFUSED at the AWS identity gate with REFUSED_IDENTITY and
                        exit code 6, and the second COMPLETED with exit code 0.
                        Acceptance was not permission to run it, a refused run is
                        not permission to run it again, and a completed run is not
                        permission to run it a third time: the implementation,
                        execution and empirical-qualification gates are never
                        collapsed into one
               further AWS identity diagnosis of that refusal, any authentication or
                        SSO repair, and any retry -- the cause is UNDIAGNOSED and
                        stays UNKNOWN; a refusal is a completed result, not
                        permission to diagnose, repair or try again
               the AWS identity gate, Terraform, secret retrieval, Secrets Manager
                        access, any provider request, any S3 qualification
                        publication and any further authenticated qualification
                        arising from ADR-0017 -- each stays separately gated, after
                        acceptance, after the refused attempt and after the
                        completed one
               full P1-P9 empirical qualification -- a third distinct gate, later than
                        implementation and later than execution, and still separate
                        and unexecuted
               broker/LEAN activity · Paper expansion · live trading

ENVIRONMENT    operational .venv and AWS SDK PRESENT / VERIFIED -- Python 3.11.9,
               boto3 1.43.83, botocore 1.43.83, pip check clean
               PYTHON DEPENDENCY LOCK ABSENT
               RANGE-CONFORMANT, NOT REPRODUCIBLY LOCKED
               the one future bounded attempt AUTHORIZED, RUN AND COMPLETED -- THE FIFTH
               FIVE AUTHORIZED ATTEMPTS TO DATE -- THE FIRST FOUR REFUSED, THE FIFTH
               COMPLETED
               FOURTH ATTEMPT REFUSED_IDENTITY AT THE AWS IDENTITY GATE
               FOURTH-ATTEMPT IDENTITY-GATE INVOCATIONS ONE -- IT DID NOT PASS; ITS
               OWN STS COMMAND INVOCATION UNKNOWN, BECAUSE REAL PRE-STS REFUSAL
               PATHS EXIST; STANDALONE DIAGNOSTIC COMMANDS ZERO; AWS NETWORK
               REQUESTS UNKNOWN
               POST-FOURTH AWS IDENTITY DIAGNOSIS COMPLETED --
               REFUSED_SSO_SESSION_MISSING_OR_EXPIRED, ONE COMMAND, EXIT CODE 255,
               ITS OWN NETWORK COUNT UNKNOWN, ZERO SSO LOGINS DURING IT, ZERO
               REPAIR ACTIONS DURING IT
               FIRST POST-DIAGNOSIS AWS SSO-LOGIN ATTEMPT COMPLETED --
               REFUSED_SSO_LOGIN,
               ONE COMMAND, TIMED OUT AFTER 420 SECONDS, NO EXIT STATUS RETURNED,
               NO LINGERING AWS CLI PROCESS, ZERO BROWSER AUTHORIZATIONS, ZERO
               DEVICE AUTHORIZATIONS, ZERO SUCCESSFUL REFRESHES, ZERO IDENTITY
               CONFIRMATIONS, ITS OWN NETWORK COUNT UNKNOWN, SSO SESSION STILL
               UNREFRESHED AFTER IT, EARLIER DIAGNOSIS UNREVISED, LIKELY CAUSE
               INTERACTIVE-SURFACE SUPPRESSION -- LIKELY, NOT PROVEN
               CORRECTED SECOND AWS SSO-LOGIN ATTEMPT COMPLETED SUCCESSFULLY --
               ONE COMMAND IN A NEW CLAUDE SESSION, LIVE CONSOLE WITH
               INHERITED STDIN, STDOUT AND STDERR, NO CAPTURED, PIPED,
               REDIRECTED, BUFFERED OR FILE OUTPUT, INTERACTIVE BROWSER/DEVICE
               FLOW
               COMPLETED, EXIT CODE 0, NO LINGERING AWS CLI PROCESS, SUCCESSFUL
               GOVERNED SSO REFRESHES ONE, MINIMAL ALLOWLISTED CHILD
               ENVIRONMENT BUILT KEY-BY-KEY, NO WHOLE-ENVIRONMENT COPY, NO
               CREDENTIAL-BEARING AMBIENT VARIABLE COPIED OR INSPECTED,
               GOVERNED PROFILE FROM A STATIC AST PARSE OF EXPECTED_PROFILE AND
               NEVER DISCLOSED, VERIFICATION URL AND ONE-TIME DEVICE CODE
               TRANSIENT IN THE LIVE CONSOLE ONLY, ITS OWN NETWORK COUNT UNKNOWN
               ONE SANITIZED IDENTITY CONFIRMATION FOLLOWED IT -- AWS STS
               GET-CALLER-IDENTITY, EXIT CODE 0, NON-EMPTY USERID, ACCOUNT AND
               ARN STRUCTURALLY PRESENT, RAW RESPONSE AND PRIVATE IDENTITY
               VALUES NEITHER DISPLAYED NOR PERSISTED, CLASSIFIED
               IDENTITY_CONFIRMED, CAPTURED BUFFERS CLEARED AFTER
               CLASSIFICATION, ITS OWN NETWORK COUNT UNKNOWN, IDENTITY
               CONFIRMED AT THE TIME OF THAT COMMAND WITH NO GUARANTEE OF
               CURRENT OR FUTURE SESSION VALIDITY, AND VERIFYING NO SECRET
               IDENTIFIER, SECRET, CREDENTIAL, BUCKET OR PROVIDER ACCESS
               FIFTH BINDING-PREFLIGHT ATTEMPT COMPLETED -- ONE PROCESS INVOCATION,
               EXIT CODE 0, CLOSED OUTCOME COMPLETED + VALIDATION_COMPLETED, LAST
               STAGE DEFINITIVELY REACHED STAGE 10, COMPOSITION STATUS
               VALIDATED_OFFLINE, PUBLIC OUTPUT EXACTLY "binding preflight
               completed" AND "offline validation completed"
               FIFTH-ATTEMPT COUNTS -- IDENTITY-GATE INVOCATIONS ONE AND PASSED,
               LICENSED-BUCKET RESOLUTIONS ONE, SECRET-IDENTIFIER RESOLUTIONS ONE,
               SECRETS MANAGER CLIENT CONSTRUCTIONS ONE, GET_SECRET_VALUE
               INVOCATIONS ONE AND ADMITTED, S3 CLIENT CONSTRUCTIONS ONE, S3 OBJECT
               OPERATIONS ZERO, PROVIDER TRANSPORT CONSTRUCTIONS ONE,
               SHARADAR/PROVIDER REQUESTS ZERO, OFFLINE COMPOSITION-PREFLIGHT
               INVOCATIONS ONE, QUALIFICATION EXECUTIONS ZERO, UNDERLYING AWS
               NETWORK REQUESTS UNKNOWN
               ONE CREDENTIAL RETRIEVED AND STRUCTURALLY ACCEPTED -- NEVER
               DISPLAYED, LOGGED, PERSISTED, HASHED, FINGERPRINTED, MEASURED OR
               SUMMARIZED; SHARADAR AUTHENTICATION UNKNOWN, NO PROVIDER REQUEST MADE
               SECRET IDENTIFIER OWNER-CONFIGURED, NOT READ BY THE FOURTH ATTEMPT,
               AND RESOLVED ONCE BY THE ENTRY POINT ON THE FIFTH
               a sixth attempt NOT AUTHORIZED
               further AWS authentication diagnosis NOT AUTHORIZED
               ANOTHER AWS SSO-LOGIN/REFRESH ATTEMPT SEPARATELY GATED AND NOT AUTHORIZED
               additional credential or Secrets Manager access NOT AUTHORIZED
               a third authenticated qualification attempt NOT AUTHORIZED -- two
               occurred; the first refused at the AWS identity gate with
               REFUSED_IDENTITY and exit code 6, its cause UNDIAGNOSED and UNKNOWN,
               and the second COMPLETED with exit code 0, reached the qualification
               runtime and made ONE PROVIDER REQUEST, with its S3 QUALIFICATION
               OPERATIONS THREE TO SIX, EXACT-REQUEST AUTHENTICATION ESTABLISHED
               and PROVIDER-WIDE AUTHENTICATION UNKNOWN
               further Sharadar/provider access NOT AUTHORIZED
               S3 object operations or publication NOT AUTHORIZED
               ingestion, backfill and update NOT AUTHORIZED
               CONTROL publication DEFERRED / NOT AUTHORIZED
               broker, LEAN, Paper and live trading NOT AUTHORIZED -- live trading
               HARD-DISABLED
               SDK/client construction outside the ADR-0015 operator boundary NOT AUTHORIZED

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
outside its own tests calls it; and its only exposed operation is offline plan validation, which
reaches no transport. Static tests prove each of those rather than asserting them.

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

### The bounded authenticated acquisition qualification — ATTEMPTED TWICE, REFUSED THEN COMPLETED

[ADR-0017](docs/decisions/ADR-0017-bounded-authenticated-sharadar-acquisition-qualification.md)
**remains ACCEPTED / IN FORCE**. **PR #33 merged** — merge commit
**`4fab37cd9468bc48b62a80e49e5a17a203870926`**, approved ADR head
**`679863fd7f540f47ae4f47aee8d5e363d72caffd`**, with exactly those two parents.

**The chronology, in order, because the order is the governance:**

1. ADR-0017 was **proposed in open PR #33 and carried no authority at that time**. That was true
   then, and it is not rewritten.
2. **PR #33 merged.**
3. **The merge activated ADR-0017's own acceptance condition.**
4. **ADR-0017 is now accepted and in force.**
5. **No implementation and no execution followed the merge**, and the status was synchronized on
   that footing.
6. **The dormant code-only implementation slice — the next separately reviewed step — was
   written and merged as PR #35.**
7. **It had never been executed at that point**, and the status was synchronized on that footing.
8. **A separately authorized first execution was then attempted, in a fresh session.** Subject
   `AAPL` and execution identifier `sharadar-auth-qual-20260830-01` were admitted unmodified by
   the committed plan grammar, and **exactly one entry-point process was invoked**.
9. **Stages 1–4 passed** — explicit operator authorization, a non-automation execution context,
   locked-plan and identity admission, and the governed-profile contract.
10. **Stage 5, the existing AWS identity gate, was invoked once and refused.** Exit code **`6`**,
    closed outcome **`REFUSED_IDENTITY`**, public output exactly
    `authenticated qualification refused: the AWS identity gate did not pass`.
11. **No retry, diagnosis, SSO login or repair followed that refusal under its own
    authorization**, and the status was synchronized on that footing.
12. **A separately authorized SSO login completed with exit code `0`.** No SSO-login count is
    revised here: authorized SSO-login attempts remain **TWO**.
13. **A separately authorized identity diagnosis then returned `IDENTITY_CONFIRMED`** —
    **expected-account resolution attempts ONE**, **STS command invocations ONE**, **STS exit code
    `0`**, **structural identity fields present YES**, **account comparison matched YES**.
14. **A separately authorized second execution was then attempted, and it COMPLETED.** **Exactly
    one entry-point process was invoked**, the **exit code was `0`**, a **closed result was
    observed**, and that closed result was **`COMPLETED`**.
15. **The qualification runtime was reached**, and **one provider request was made**.
16. **Attempt two's S3 qualification operations are bounded at THREE TO SIX** by the closed
    token's committed meaning — **exactly three `PutObject` invocations** and **zero to three
    conditional `HeadObject` invocations** — while **how many objects were newly written stays
    NOT ESTABLISHED**.
17. **No third attempt, retry, diagnosis, SSO login or repair followed**, and none is authorized.

**The authenticated acquisition entry point is IMPLEMENTED, ATTEMPTED TWICE — REFUSED, THEN
COMPLETED.**
`scripts/sharadar_authenticated_qualification.py` exists and **refuses by default**: an ordinary
import performs no lookup, constructs no client, opens no socket and reads no environment variable.
Its CLI is **exactly three arguments**, and every credential, dataset, window, page, retry, bucket,
bulk, ingestion and CONTROL spelling is **refused by name**.

**The accepted composition root was extended, not duplicated.**
`execute_qualification_acquisition` was added to the same module that already builds the client, the
store and the runtime — a second root would have meant widening the single-constructor guard from
one file to two. **`QualificationRuntime.execute` now has exactly ONE ADR-0017 production
caller**, reachable only through the entry point's authorized branch.

**The repository now has exactly TWO production call sites overall**, and the two are kept
apart on purpose: that unchanged ADR-0017 composition, and the separate dormant
ADR-0018 / ADR-0019 / ADR-0020 qualification acquisition path merged by PR #48. **The second
caller does not alter, broaden or become reachable from ADR-0017**, and **assessment read
composition remains separate from acquisition**. **Before that dormant implementation merged
the ADR-0017 caller was the only one** — true then, and not rewritten.

**Implementing an operator surface was not permission to use it, one refused attempt is not
permission to make a second, and one completed attempt is not permission to make a third.**

```
authenticated entry points implemented      ONE
authenticated qualification attempts        TWO -- ONE REFUSED, ONE COMPLETED
entry-point process invocations             TWO -- exactly one per attempt

ATTEMPT ONE -- REFUSED
closed outcome                              REFUSED_IDENTITY   ·   exit code: 6
last stage definitively reached             STAGE 5 -- the AWS identity gate
stages 1-4                                  PASSED
AWS identity-gate invocations               ONE -- refused
licensed-bucket resolutions                 ZERO
Terraform command invocations               ZERO
secret-identifier resolutions               ZERO
KALPAMANI_SHARADAR_SECRET_ID reads          ZERO
Secrets Manager client constructions        ZERO
get_secret_value invocations                ZERO
credential retrievals by this attempt       ZERO
S3 client constructions                     ZERO
provider transport constructions            ZERO
qualification-runtime executions            ZERO
application-level provider fetches          ZERO
Sharadar/provider requests                  ZERO
PutObject                                   ZERO   ·   conditional HeadObject: ZERO
S3 object-byte reads                        ZERO
S3 object operations for qualification      ZERO
CONTROL operations                          ZERO
.runtime/ writes from this attempt          ZERO
underlying AWS/network interactions         UNKNOWN -- no count is established
STS command invocations by the gate         UNKNOWN -- real pre-STS refusal paths exist
cause of the identity refusal               UNDIAGNOSED -- not inferred, not repaired

ATTEMPT TWO -- COMPLETED
entry-point process invocations             ONE
entry-point exit code                       0
closed result observed                      YES   ·   closed result: COMPLETED
qualification runtime reached               YES
qualification-runtime executions            ONE
provider requests                           ONE -- no further call is inferred
PutObject invocations                       EXACTLY THREE
conditional HeadObject invocations          ZERO TO THREE -- only after a 412
S3 qualification operations                 THREE TO SIX
publication state unknown                   NO
complete acquisition record                 EXISTS -- one per planned request
newly written objects                       NOT ESTABLISHED -- a bound is not a count
already-present identical objects           NOT ESTABLISHED
object identifiers, keys, digests, sizes    NOT ESTABLISHED -- and never derived here
underlying AWS/network interactions         UNKNOWN -- no count is established

CUMULATIVE
authenticated qualification attempts        TWO
qualification-runtime executions            ONE
known provider requests                     ONE
S3 qualification operations                 THREE TO SIX -- attempt one ZERO,
                                            attempt two THREE TO SIX
exact-request authentication                ESTABLISHED -- for that one governed request
provider-wide authentication                UNKNOWN -- one answered request is not
                                            every request
subscription-wide entitlement               UNKNOWN
production provider selected                NONE   ·   G1: OPEN   ·   G2: OPEN
P1-P9 executions                            ZERO -- separate and unexecuted
ingestion and trading operations            ZERO
CONTROL operations                          ZERO
credential retrievals established by count  ONE -- the fifth binding-preflight attempt's;
                                            attempt two's count is NOT ESTABLISHED
                                            by count, though its credential stage
                                            necessarily passed
binding-preflight attempts                  FIVE -- unchanged
authorized AWS SSO-login attempts           TWO -- unchanged
a third authenticated attempt               NOT AUTHORIZED
```

**Implementation, execution and full empirical qualification remain three distinct gates** that are
never collapsed into one. The first two have now been *entered*; **none of the three is closed**,
and a completed execution closes neither the execution gate for a further run nor the empirical one.
A **third** execution of the surface is separately gated and **NOT AUTHORIZED**, and so are a further
AWS identity gate invocation, Terraform, secret retrieval, Secrets Manager access, any provider
request and any S3 qualification publication arising from it.

**What attempt one established, and what it did not.** It proves exactly one thing: that at that
moment, in that ordered sequence, **the governed AWS identity gate did not pass**. It
establishes **nothing** about the secret identifier, the stored secret, the credential, Sharadar
authentication, the licensed bucket, dataset accessibility, response content, row count, schema,
subject correspondence, data quality, price-feed provenance, Q7, P1–P9 qualification, provider
selection, ingestion readiness, or G1 and G2. It equally does **not** establish that the credential,
the secret or the configuration is faulty: the refusal is **upstream of all of them**.

**What attempt two established, and what it did not.** It establishes that **one entry-point process
was invoked**, that it **exited `0`**, that a **closed result was observed** and was **`COMPLETED`**,
that the **qualification runtime was reached**, and that **one provider request was made**. Reaching
the qualification runtime means **no earlier stage refused**, because a refusal raises and no later
stage runs after an earlier refusal — that is what the committed order guarantees.

**`COMPLETED` is a closed token with a committed meaning, and that meaning is read from the code.**
This is a **semantic derivation from the already-observed result and the accepted contracts**, not a
new observation: no AWS call, provider request, S3 read or private-report inspection contributed to
it. `_classify_result` returns the public `COMPLETED` **only** for
`QualificationOutcome.COMPLETED`; `QualificationRunResult.__post_init__` **refuses** that outcome
unless there is **no failure**, **no partial state**, **`publication_state_unknown` is `False`** and
**every planned request has a complete acquisition record**; the locked plan holds **exactly one
request**; one completed acquisition calls `publish_bronze_payload` **exactly once**; that function
calls `put_if_absent` **exactly three times** — claim, payload, record — with **no short-circuit**;
each `put_if_absent` issues **exactly one conditional `PutObject`** with **no retry loop**; and a
`HeadObject` is issued **only after a `412`**, **at most once per `PutObject`**.

**So attempt two establishes bounds, and states them:** **`PutObject` invocations EXACTLY THREE**,
**conditional `HeadObject` invocations ZERO TO THREE**, **S3 qualification operations THREE TO SIX**,
**publication state unknown NO**, and **a complete retained acquisition record EXISTS**.

**What the token does not fix stays unfixed, and a bound is not a count.** How many of the three
objects were **newly written objects NOT ESTABLISHED**; how many were
**already-present identical objects NOT ESTABLISHED**; and so is the exact `HeadObject` count within
its bound. **No object identifier, key, digest, size, timestamp or content is established, disclosed
or derived**, and none of it is resolved by reading S3 or a private report.

**`COMPLETED` is a command status, not a verdict.** It is **not** qualification passed, **not** the
provider accepted, **not** a provider selected, **not** a closure of G1, **not** a closure of G2,
**not** a completion of Phase 3, **not** production readiness, **not** CONTROL readiness and **not**
live-trading readiness. It establishes **no data quality**, **no schema correctness** and **no P1–P9
result**.

**Authentication is two separate facts, and collapsing them is the error this guards.** A request the
provider answered is **exact-request authentication ESTABLISHED** — the governed credential was
accepted for that one governed request, because `SharadarClient.fetch` returns a body on **no status
other than `200`**. **Provider-wide authentication UNKNOWN**, and **subscription-wide entitlement
UNKNOWN**: one answered request is not a claim about every dataset, every window or the subscription.
**No additional provider call is inferred**, and **no provider is selected**: a completed
qualification request selects nothing.

**The cause was not diagnosed, and is not inferred here.** *The identity gate refused* is not *the
SSO session was missing*, *the SSO session was expired*, *the credential is defective* or *the
provider failed*. The earlier `REFUSED_SSO_SESSION_MISSING_OR_EXPIRED` diagnosis and the later
successful SSO refresh and `IDENTITY_CONFIRMED` confirmation are **separate historical events**
about earlier binding-preflight work; a point-in-time identity confirmation **guarantees no current
or future session validity**, and none of them explains this refusal. **Why the gate refused is
UNKNOWN**, and a bounded diagnosis is a **separate** authorization that has not been given.

**The STS question is answered statically, and the answer is UNKNOWN.** The committed
`identity_gate()` in `scripts/aws_foundation_verify.py` has **two refusal paths that return before
its `sts get-caller-identity` command is reached** — an `AWS_PROFILE` that does not equal the
governed constant, and a local `terraform.tfvars` that yields no twelve-digit account binding, which
is a plain local file read. Because a **real pre-STS refusal path exists**, the STS command
invocation for this attempt is recorded as **UNKNOWN**, not as one — and it is not inferred from the
exit code or from any prior attempt. **No STS network-request count is stated, and underlying AWS
network interactions stay UNKNOWN**, because a CLI or SDK call can resolve locally and fail before
anything leaves the machine.

**Everything attempt one did not reach is unchanged.** No secret identifier was resolved and
`KALPAMANI_SHARADAR_SECRET_ID` was **not read**; no Secrets Manager client was constructed and
`get_secret_value` was **not invoked**; **no credential was retrieved by that attempt**. No S3
client, no provider transport, no qualification-runtime execution, **no provider request**, no
`PutObject`, no `HeadObject`, no object-byte read, no CONTROL operation, no `.runtime/` write and no
P1–P9 execution. **Cumulative credential retrievals established by count remain ONE**, from
binding-preflight attempt 5, and **attempt two's credential-retrieval count is NOT ESTABLISHED**
by count, though reaching the qualification runtime means its credential stage did not refuse.
**Exact-request authentication is ESTABLISHED for attempt two's one governed request, and
provider-wide authentication remains UNKNOWN.**

**Neither attempt is a sixth binding-preflight attempt.** Binding-preflight attempts remain
**FIVE**, the fifth of which completed offline validation; that count is untouched by an
authenticated qualification attempt, which is a different surface under a different authorization.

**A third authenticated qualification attempt is NOT AUTHORIZED · further AWS identity diagnosis is
NOT AUTHORIZED · another AWS SSO refresh or login is NOT AUTHORIZED · credential access, Secrets
Manager access, provider access, any S3 publication and full empirical qualification each remain
separately gated and NOT AUTHORIZED.** A refusal is a completed result, not permission to repair and
try again — and **a completed run is not permission to run again either**.

**The accepted architecture is preserved by the implementation, not reinterpreted.** ADR-0012's rule
that **one request = one durable acquisition** holds; the response is published **byte for byte**
through the licensed Bronze bridge; the acquisition runtime keeps its **opaque-payload boundary**
and **no parser was introduced** anywhere in the entry point, the composition root, the runtime, the
transport or the publisher; the mode is **`AcquisitionMode.QUALIFICATION`**, declared and never
inferred, with **no fourth mode introduced**; the retrieval is **one provider request** with **no
pagination** and **no automatic retry**, over a deterministic **seven-day trailing window** ending
the UTC day before invocation; publication is **licensed Bronze** only, creating **three durable
artifacts** in **exactly three PutObject operations**, with **zero to three conditional HeadObject
metadata checks only after a 412**, **zero object-byte reads**, **zero `.runtime/` writes** and **no
extra qualification report**; and **CONTROL publication stays ZERO and forbidden**. Each of those is
a synthetic test that counts what a fake was asked for, not a sentence repeated here.

**The other two scripts are unchanged and still separate.**

| Candidate | What it actually is |
|---|---|
| `scripts/sharadar_private_qualification.py` | the **public-test-token** P1–P9 harness — five tables, payload parsing, local staging, broader persistence |
| `scripts/sharadar_binding_preflight.py` | the **offline** binding/composition preflight — terminates at `preflight_qualification_composition` by design |
| `scripts/sharadar_plan_check.py` | offline plan validation only |

Neither is imported, invoked, repurposed or changed by the new entry point, and a test asserts it.

**The full P1–P9 empirical qualification remains separate and unexecuted.** It is the
public-test-token harness, it is not reused as the authenticated runner, and no AI session may run
it. It is the **third** gate, later than implementation and later than execution.

**Nothing else is resolved by implementing this, by the refused attempt, or by the completed one.**
**No provider is
selected**, **full P1–P9 empirical qualification remains separate and unexecuted**, **G1 OPEN · G2 OPEN
· G3 CLOSED · G4–G7 OPEN**, ADR-0005 **PROPOSED**, INC-0002 **OPEN**, Phase 3 **NOT COMPLETE**,
CONTROL publication **DEFERRED**, live trading **HARD-DISABLED**. Q7 stays
**`PUBLICLY_UNRESOLVED`**.

### The bounded private empirical qualification — ACCEPTED, and architecture only

[ADR-0018](docs/decisions/ADR-0018-bounded-private-empirical-sharadar-qualification.md) designs
the package that would actually produce useful P1–P9 evidence. **ADR-0018: ACCEPTED / IN FORCE**
— **PR #39 merged**, merge commit **`97e7ce57bb90303c78c2a1a4bc3ac2301b60f694`**, approved
ADR head **`25ee0b0a6ab17c1fea7e2fa4ccd72ce8b2864780`**.

Its conditional status line took effect on that merge, so **the conditional acceptance event has
occurred**. **While PR #39 was open it was proposed and carried no authority** — exactly the
state ADR-0017 was in before PR #33 merged. That is a historical fact about those days, it stays
true, and it is **not** rewritten as though the document had authority before its merge.

**The merge approved architecture only, and nothing else.**

| | |
|---|---|
| **Approved by the merge** | the evidence inventory · the P1–P9 ceilings · the two-process split · the deterministic private locator · the operation arithmetic · the two least-privilege roles · the parser, evaluator and report boundaries · the deletion-runbook clarification |
| **NOT approved by the merge** | implementation under `src/` · a new entry point · an IAM role · a Terraform plan or apply · a binding preflight · Run A · Run B · an assessment run · a provider request · an S3 operation · a credential retrieval · a private report · a P1–P9 execution · a provider selection · a G1 or G2 decision |

**The merge authorized no implementation, no infrastructure mutation and no execution.** Each of
those is a gate of its own, and acceptance of a design opened none of them.

**The clarification amendment is EFFECTIVE — PR #42 merged.** Merge commit
**`28239514b9e4e13f55ee98fa50877077e70bd593`**, approved clarification head
**`579259a62ff7561ae2991f3923ea8aa1d0064be8`**. An independent
read-only review of the offline implementation candidate returned
**`BLOCKED_ADR_CLARIFICATION_REQUIRED`** and named two gaps in the accepted architecture: the
1,800-second ceiling had no stated scope, clock or enforcement point, and the assessment
arithmetic covered only one 48-request locator, which cannot reach P1's accepted `TESTED`
ceiling. **The owner approved two decisions** — the **1,800-second acquisition deadline** is one
actual elapsed-time deadline on an injected monotonic clock over the complete acquisition
execution phase, and **one combined private assessment evaluates Run A and Run B together** after
Run B. Both were written into ADR-0018 by a **documentation-and-governance-only** pull request,
and **the conditional effectiveness event has occurred**: **ADR-0018's total elapsed acquisition
deadline clarification is now effective**, and **ADR-0018's combined Run A / Run B assessment
clarification is now effective**.

**While PR #42 was open the clarification was proposed and carried no authority.** That is a
historical fact about those days, it stays true, and it is **not** rewritten as though the
clarification had always been effective — the same treatment ADR-0018's own conditional
acceptance was given when PR #39 merged. **The merge approved clarification of architecture
only**, and **the clarification merge authorized no implementation, no infrastructure mutation
and no execution**. **ADR-0018 itself remains ACCEPTED / IN FORCE as architecture only**, and the
now-effective amendment **adds no authorization of any kind**.

**The ADR-0018 offline implementation is MERGED and DORMANT — PR #41 merged.** Merge commit
**`3ddd7d40741bb9a50ae4fc5452324ddbfb5e1ec0`**, approved implementation head
**`96daac7963d936f231b37847579c5f28bb313760`**. **PR #41 merged the ADR-0018 offline implementation**, and
**the merged implementation is dormant**. **The merge did not deploy infrastructure**, **did not
authorize or execute Run A, Run B or the combined assessment**, **did not close G1 or G2**, **did
not select a provider** and **did not authorize live trading**. **Merging an implementation
authorized no execution, no infrastructure deployment and no run.**

**The fixed 48-request assessment-boundary correction is MERGED — PR #44 merged.** Merge commit
**`c945970613b80bfd4f42acc4f3acb4814895eb42`**, approved correction head
**`78b4425077e65eeb12dfd24b35825741370e0e0f`**. **Independent review found that PR #41's initial assessment
pair validation enforced only run-to-run count consistency** — a pair that agreed with itself at
some other count would have been admitted. **PR #44 compiled ADR-0018's requirement that both runs
contain exactly 48 planned and 48 completed requests**, and **PR #44 also prevents assessment
accounting from scaling from a locator-supplied non-48 count**. **The corrected valid assessment
envelope remains 194 `GetObject`, one report `PutObject`, 0–1 conditional report `HeadObject` and
195–196 total assessment S3 operations**, and **invalid non-48 pairs refuse before record or
payload reads**. **The correction changed no ADR, durable locator schema, infrastructure, provider
behaviour, deadline, P1–P9 ceiling, report format or public authorization.**

**The two merges are separate events, and neither is read through the other.** **While PR #41 was
open it was an unmerged implementation candidate**, and **before PR #41 merged, the offline package
and its two dormant entry points were absent from main** — historical facts about those days that
stay true and are not rewritten. **PR #41 merged before the missing fixed-count validation was
corrected**; **the defect remained dormant because execution was not authorized**; and **PR #44
subsequently corrected the implementation on main**. **PR #41 is not described as having passed the
later PR #44 correction review.** **No Run A, Run B or combined assessment occurred before, during
or after either merge**, and **the premature merge is no evidence of execution or of empirical
qualification**.

**The candidate framing is superseded, and the correction history is kept.** The offline
implementation was **corrected against the now-authoritative clarification** under a separately
authorized implementation correction, and **the independent re-review has since occurred and
produced the fixed-count correction merged as PR #44**. **Clarifying an architecture is not
correcting an implementation**, and the clarification pull request corrected none: it changed no
source file, no entry point and no test of that implementation.

**The licensed read surface is now stated precisely rather than as an absence.** **The bounded
assessment-only read implementation now exists in committed code**, **it is dormant and not
deployed**, **it permits no S3 listing**, **it is not a general read surface**, and **it has never
been executed against licensed objects**. **No locator, record, payload or report has been read by
the empirical package**, **the acquisition process remains write-only**, and **the ordinary
ingestion path remains unable to use the qualification read surface**. **A reading implementation
existing is not private evidence existing**: nothing has been run, so nothing has been produced.

**One sanitized incident is recorded, and it authorizes nothing.** The implementation session
performed an **unauthorized directory listing beneath the private runtime area**. It **observed
owner-side filenames but read no file contents**. The independent review **did not reproduce the
listing**, and **found no evidence that observed private metadata entered tracked work** — **no
tracked contamination was found by the read-only review**. **The filenames themselves are
intentionally not disclosed**, here or anywhere else. **This incident does not authorize
private-directory inspection, and it does not authorize further diagnosis**: `.runtime/` stays
uninspected, and repository-state questions are answered from Git's tracked tree and index alone.

**Implementation, infrastructure mutation and execution are three separate gates, and they are
never collapsed into one.** That is the rule five binding-preflight attempts and two
authenticated qualification attempts have each been held to, and this slice inherits it rather
than restating a weaker version.

**It supersedes nothing, and it rewrites no history.** ADR-0011's statement that the licensed
store has **no read surface** was true of the store it authorized and stays true of it; the
designed read component is **separate and narrowly scoped**, for a different actor, and widens
neither `ResearchObjectStore` nor the writer-side S3 client protocol. **ADR-0017's accounting —
exactly three `PutObject`, zero to three conditional `HeadObject`, zero object-byte reads — is
untouched**: the surface designed here is a **different** surface with its own accounting, and it
may never be reached through the ADR-0017 entry point.

**Why the package exists.** Attempt two under ADR-0017 completed, made one provider request and
published a single seven-day, single-subject, single-dataset acquisition. That is bounded-plumbing
evidence and is accepted as such. **It is not empirical provider qualification: no P1–P9 minimum
is met by one row of one dataset for one subject.** Its retained response also has no digest-free
locator, and the licensed store has no listing surface — deliberately, because a producer that
could list the store could enumerate what a vendor sent. **Those three objects will not be located
or assessed**, they **stay covered by prefix-based deletion**, and that disposition is not
repaired retroactively.

#### The designed inventory

**Eight private subject classes, recorded as classes and never as names.** Concrete names stay out
of Git, documentation, command arguments and public output, and arrive later through a
**git-ignored, owner-only private input** — which securities the owner chose to evaluate is
evaluation information under the personal-use licence, and a name in a tracked module or on a
command line would put it in Git history and in every process listing.

```text
1 active long-history large-cap dividend payer with an in-window split
2 active spinoff parent            3 active spinoff child
4 delisted approximately 5 years ago
5 delisted approximately 10 years ago
6 delisted approximately 15 years ago
7 ticker-change or numeric-suffix reassignment case
8 active small-cap control with no corporate action in the window
```

| Dataset | Window | page limit | max pages |
|---|---|---|---|
| `tickers` | **none — snapshot, a window is refused** | 100 | 2 |
| `stocks` | **1998-01-01 → `T−1`** | 10,000 | 2 |
| `actions` | **1998-01-01 → `T−1`** | 10,000 | 2 |

**Page two is a completeness probe, not an invitation to paginate.** Sorting is a forbidden
request parameter and the row limit defaults to a silent truncation boundary, so an empty second
page is the only available proof the first was complete; a non-empty second page means truncation,
and every row-count-dependent conclusion for that pair is refused rather than reported.

```text
requests per run            48 = 8 subjects x 3 datasets x 2 pages
provider retry policy       max_attempts = 1 -- ZERO provider retries, ARITHMETICALLY FORCED:
                            48 requests against the compiled retry budget of 32 leave no room
max response bytes          4 MiB      max run bytes    64 MiB
per-request timeout         30 s       pacing           at least 1 s
execution                   SEQUENTIAL ONLY
acquisition elapsed deadline  1,800 s -- one ACTUAL elapsed-time deadline on an
                            INJECTED MONOTONIC CLOCK, not compile-time arithmetic
runs                        TWO, at least eight calendar days apart
                            each separately authorized, each a distinct execution identity
max provider requests       96 across both runs
```

**Run A and Run B are never one standing authorization**, and neither is a permission for the
other. Minimum qualification, this package and production backfill stay three separate scales;
backfill is also a different acquisition mode, and **`BACKFILL` and `UPDATE` remain NOT
AUTHORIZED**.

#### The 1,800-second acquisition deadline

**The 1,800-second ceiling is one actual elapsed-time deadline, and not compile-time arithmetic.**
It is **measured on an injected monotonic clock**, and **wall-clock calendar time must never be
used for deadline arithmetic** — a clock adjustment must not be able to shorten or lengthen a
licensed acquisition. It **starts immediately before the first provider request, at acquisition
stage 11**, and **ends only when acquisition reaches a terminal locator result, at acquisition
stage 13**. **The ceiling is not raised**: lowering it is a configuration choice, raising it is an
ADR change.

```text
COVERED, the complete acquisition execution phase
    provider requests                     inter-request pacing
    local validation and digest work      three Bronze publications per completed request
    conditional metadata resolution       partial or complete locator construction
    locator publication                   permitted locator retry
    terminal classification

NOT COVERED, acquisition stages 1-10
    authorization · private input · identity · binding · credential
    dependency construction · offline preflight
    -- gates that happen before acquisition execution begins
```

**No provider or S3 operation may start after the deadline**, and **no operation may be started
merely in the hope that it completes before it.** Remaining budget is checked **before** every
provider request, pacing delay, Bronze write, metadata-resolution call, locator write and locator
retry. **A provider request may start only when the remaining budget covers its whole downstream
obligation** — its own configured maximum duration, its three Bronze publications, the at most
three conditional metadata resolutions those may trigger, and the reserved locator-terminal
budget. **Pacing is never silently shortened**: a pacing delay may be refused, which halts the
run, and it may not be truncated to fit.

```text
if insufficient budget remains          THE RUN HALTS before starting another provider request
completed requests                      REMAIN COMPLETED -- a deadline is not a rollback
an unpersisted response                 IS NOT A COMPLETED REQUEST
the locator                             attempted ONLY while enough reserved budget remains
                                        for its permitted terminal sequence; PARTIAL on a halt
no safe locator attempt                 the accepted closed non-addressable result
                                        LOCATOR_NOT_PUBLISHED -- IT MUST NOT CLAIM A LOCATOR EXISTS
deadline exhaustion                     a CLOSED, SANITIZED status -- RUN_DEADLINE_EXHAUSTED
public output                           NO exception text, private identifier, key, subject,
                                        digest, vendor row or timing trace
deadline exhaustion authorizes          NOTHING -- no retry, no resume, no new execution identity;
                                        a future retry or re-run is a SEPARATE authorization
```

**The SDK must not be able to defeat the deadline.** Acquisition-side AWS SDK clients are
configured explicitly: **SDK automatic retries disabled for qualification S3 calls**, **adaptive
or hidden retry mode forbidden**, an **explicit bounded connect timeout**, an **explicit bounded
read timeout**, the application-level locator retry **is the only locator retry**, **Bronze writes
remain unretried**, and the permitted locator retry classifications stay **`THROTTLED` and
`TRANSIENT`** and nothing else.

<!-- RETIRED-ARITHMETIC BEGIN: ADR-0018 original, superseded by ADR-0019, no longer governing -->

> **HISTORICAL — ADR-0018 ORIGINAL ARITHMETIC. SUPERSEDED BY ADR-0019; NO LONGER GOVERNING.**
> The sub-budget arithmetic that follows, to the end of this subsection, is ADR-0018's original
> accepted arithmetic, kept as the record of what ADR-0019 amended.
> **The governing deadline arithmetic is ADR-0019's**: `L >= 3 * T_s3 + C`, a per-request S3
> obligation of `3 * T_s3`, `T_req + P + 3 * T_s3 + L <= D`, and
> `remaining >= T_req + 3 * T_s3 + L`, at `D = 1800 seconds`. Those are **authoritative
> architecture requirements that the dormant production code does not yet implement** — see
> *The infrastructure-feasibility gap, and ADR-0019* below. What ADR-0019 amended here is the
> per-request and locator S3 allowances; the 1,800-second deadline itself, the injected
> monotonic clock, the SDK-retry and socket-timeout requirements and the halt-and-`PARTIAL`
> behaviour are **preserved unchanged**.

**The sub-budgets are required implementation constants, not numbers invented here.** Three values
are already accepted — the deadline `D = 1,800 s`, the provider ceiling `T_req = 30 s` and the
minimum pacing `P = 1 s`. Every other term is a **required implementation constant whose proposed
numerical value must be reviewed with the correction pull request**:
`S3_CONNECT_TIMEOUT_SECONDS`, `S3_READ_TIMEOUT_SECONDS`, the derived `S3_OPERATION_CEILING`
(`T_s3`), `LOCATOR_CONSTRUCTION_ALLOWANCE` (`C`) and `LOCATOR_TERMINAL_RESERVE` (`L`). The reserve
must **cover `4 * T_s3 + C`** — three locator `PutObject` attempts, at most one locator
`HeadObject`, and deterministic construction and terminal classification — and **configuration
that cannot fit is refused, not clamped**:

```text
T_s3 > 0        C >= 0        L >= 4 * T_s3 + C        L < D
T_req + P + 6 * T_s3 + L  <=  D          at least one full request-and-publish cycle,
                                         plus the reserve, must fit inside the deadline
per-request admission:  remaining >= T_req + 6 * T_s3 + L
```

**And the uncomfortable consequence is recorded rather than smoothed over.** At the compiled worst
case `48 * (30 + 1) = 1488 s` leaves **312 seconds** for 144 Bronze `PutObject`, up to 144
conditional `HeadObject` and the locator — about **1.08 seconds per S3 operation**, which is not a
defensible connect-plus-read bound. **The 1,800-second deadline is therefore a safety bound on
elapsed time, and not a guarantee that 48 requests complete.** A slow provider means the run halts
short, publishes a **`PARTIAL`** locator, and the assessor **refuses to evaluate it**; the owner
reviews the halt and re-runs under a **separate authorization** and a **new execution identity**.

<!-- RETIRED-ARITHMETIC END -->

#### The honest ceilings

A ceiling is what a run may **at most** report. A run may fall short of one; no run may exceed one.

| | Ceiling |
|---|---|
| **P1** | `PARTIALLY_TESTED` after Run A, **at most `TESTED`** after Run B and reachable **only through the combined Run A / Run B assessment**. Information-time resolution **stays bounded regardless of outcome** — the vendor's update column is date-granular, and a date cannot supply an instant |
| **P2** | **at most `PARTIALLY_TESTED`.** Sampled delisted-history existence **is not proof of the provider's population-wide survivorship claim** |
| **P3** | the **schema question can reach `TESTED`**; announcement timing **remains approximated** where the field is absent |
| **P4** | `DOCUMENTATION_RESOLVED` — classification history **cannot become empirically historized from a snapshot table** |
| **P5** | **realistically at most `PARTIALLY_TESTED`** — split and dividend limbs may be tested, and the **spinoff limb stays inconclusive while the provider's semantics are undocumented** |
| **P6** | **`DEFERRED` to Phase 3B** |
| **P7** | **`DEFERRED` to Phase 3B and EDGAR** |
| **P8** | **`DEFERRED` to Phase 3B and EDGAR** |
| **P9** | `DOCUMENTATION_RESOLVED` — price information origin stays **`PROVIDER_DERIVED`** and **`PUBLIC_PIT` is not reachable from this evidence** |

**No aggregate verdict exists anywhere in the design** — no aggregate pass, no qualified, no
approved, no proceed, no ready, no provider-selection value. Provider selection is **G1**, and G1
is an owner decision taken by a person reading evidence, never a value a program returns.

**P1 semantics, exactly.** **Run A evidence alone has a P1 ceiling of `PARTIALLY_TESTED`** — one
observation cannot show that anything changed. **The combined assessment may raise P1 to at most
`TESTED`**, and only when **both complete executions are valid**, **the eight-day separation is
satisfied**, **corresponding observations can be compared**, and **the comparison supplies the
required change-detection evidence**. **Date-granular provider information still cannot establish
an instant**, so **the information-time limitation remains explicitly bounded even when P1 reaches
`TESTED`**. **Missing, incomparable, truncated, schema-drifted or insufficient cross-run evidence
never becomes a weaker pass**; **P1 may remain `PARTIALLY_TESTED` or insufficient after Run B**,
and **`TESTED` is a ceiling, not an expected outcome**. **No P1 result is an aggregate provider
verdict, and no P1 result is a G1 or G2 decision.**

#### The deterministic private locator

```text
licensed/qualification/sharadar/locators/<execution-id>.json
```

**One per execution, published last, and the physical path never appears in public output.** An
object key here binds a name **and** a content address, and the address comes from the payload —
which is exactly why attempt two is unaddressable. The locator resolves that by being **the one
object addressed by name**: it is retrieved from the execution identity alone and validated
against its closed schema and size ceiling afterwards, while **every object it references is
retrieved by name and expected digest, with the full-object checksum and byte count verified
before any parsing**.

```text
classification         LICENSED        ordering          published LAST
addressing             from a private execution identity -- NO S3 LISTING, anywhere
append-only            conditional publication, never overwritten
schema                 CLOSED, no free-text field       size ceiling  256 KiB
binds                  the plan and the private inventory, by digest
binds per object       claim, payload and record -> exact key, expected digest,
                       byte count, disposition
records                planned and completed request counts
                       COMPLETE or PARTIAL, and publication_state_unknown
never                  a cross-execution index, a bucket, an account, a credential,
                       a provider URL or a vendor row
never                  committed, and never handed to an AI session
deletion               inside the licensed qualification/ prefix
```

**A `PARTIAL`, missing, collided, ambiguous or unverified locator fails closed**, and the assessor
refuses to evaluate it — a `PARTIAL` locator preserves accounting and grants no evaluation. There
is **no fallback that reconstructs evidence by listing, probing or guessing**, because adding one
would reintroduce the capability this architecture removes. **There is no replay**: a genuine
re-run reads a new retrieval instant, so the append-only store refuses it, and a refetch needs a
**new explicit execution identity**.

#### The arithmetic, nominal and maximum

<!-- RETIRED-ARITHMETIC BEGIN: ADR-0018 original, superseded by ADR-0019, no longer governing -->

> **HISTORICAL — ADR-0018 ORIGINAL ARITHMETIC. SUPERSEDED BY ADR-0019; NO LONGER GOVERNING.**
> The nominal and maximum acquisition counts that follow are ADR-0018's original accepted
> arithmetic. **The governing acquisition arithmetic is ADR-0019's**: acquisition `PutObject`
> **145 to 147**, acquisition `HeadObject` **exactly 0**, acquisition `GetObject` **exactly 0**,
> and two successful runs **290 to 294** — **authoritative architecture requirements that the
> dormant production code does not yet implement**. Only the counts are retired: the locator
> retry policy stated between the two blocks below, and the assessment arithmetic further down at
> **195 to 196**, are **preserved unchanged by ADR-0019**.

**Nominal** — 48 requests, all complete, locator published on the first attempt:

```text
provider requests        exactly 48        provider retries        ZERO
Bronze PutObject         exactly 144       locator PutObject       exactly 1
total PutObject          exactly 145
conditional HeadObject   0 to 145 -- only after a 412, at most one per PutObject
object-byte GetObject    ZERO   ·   S3 listing  ZERO   ·   CONTROL  ZERO
total S3 operations      145 to 290
```

**Maximum** — the locator may be retried **at most twice**, and **only** on the closed
classifications `THROTTLED` and `TRANSIENT`. Every retry is the same conditional write with
**byte-identical content**, so it can resolve an unresolved condition and can never overwrite,
duplicate or corrupt. **Retry is forbidden after `ACCESS_DENIED`, `NOT_FOUND`, `INVALID_RESPONSE`,
`INVALID_CONFIGURATION`, `UNKNOWN` or a genuine collision** — and `INVALID_RESPONSE` and `UNKNOWN`
are excluded precisely because **no retry may follow an ambiguous or unclassified result**.

```text
Bronze PutObject         exactly 144 -- Bronze writes are NEVER retried
locator PutObject        at most 3
maximum total PutObject  147
conditional HeadObject   0 to 145 -- 144 Bronze, plus AT MOST ONE locator
maximum S3 operations    147 to 292
maximum, both runs       2 x 292 = 584
```

<!-- RETIRED-ARITHMETIC END -->

**A complete run reports `144 <= PutObject <= 147`, as the real observed invocation count.** It is
**not "exactly 145" when a retry occurred**, and the public counters report what happened rather
than what was planned.

**Assessment, exact formulas — one COMBINED assessment over BOTH executions.** For two
`COMPLETE` locators over `R` planned requests each and `E` acquisition executions, `R = 48` and
`E = 2`:

```text
provider requests        ZERO      credential retrievals     ZERO
locator GetObject              E = 2
acquisition-record GetObject   E x R = 96       payload GetObject   E x R = 96
acquisition-claim GetObject    ZERO -- claims are validated from the locator, not retrieved
total GetObject          E x (2R + 1) = 194
report PutObject         1 -- NOT retried    conditional HeadObject  0 to 1
S3 listing  ZERO   ·   CONTROL  ZERO
total S3 operations      E x (2R + 1) + 1 to E x (2R + 1) + 2 = 195 to 196
```

**Refused-pair arithmetic.** Both locators, and the pair relationship, are validated **before any
acquisition record or payload is read**. If the assessment refuses during that validation:

```text
locator GetObject        0 to 2
acquisition-record GetObject   ZERO      payload GetObject         ZERO
acquisition-claim GetObject    ZERO      report PutObject          ZERO
conditional HeadObject   ZERO            every other S3 operation  ZERO
provider and credential operations       ZERO
-- NO payload is read on a refusal
```

**If failure occurs after both locators pass, the actual observed counters are preserved and
reported. Never report nominal counts as observed counts.**

<!-- RETIRED-ARITHMETIC BEGIN: ADR-0018 original, superseded by ADR-0019, no longer governing -->

> **HISTORICAL — ADR-0018 ORIGINAL ARITHMETIC. SUPERSEDED BY ADR-0019; NO LONGER GOVERNING.**
> **The governing whole-package envelope is ADR-0019's**: two successful acquisition runs
> **290 to 294**, the combined assessment **unchanged at 195 to 196**, and the whole successful
> package **485 to 490** — an **authoritative architecture requirement that the dormant
> production code does not yet implement**.

**Whole-package envelope**, with the two acquisition runs and the one combined assessment:

```text
two acquisition runs       290 to 584 S3 operations
combined assessment        195 to 196 S3 operations
whole empirical package    485 to 780 S3 operations
```

`485 = 290 + 195` and `780 = 584 + 196`.

<!-- RETIRED-ARITHMETIC END -->

**The superseded canonical arithmetic is gone.** A one-locator assessment is no longer canonical,
and neither is its read total of 97, its operation total of 98-to-99, or the 196-to-198 total that
assumed one assessment per run. **These are SDK-method invocation counts, and underlying AWS or
network interactions remain UNKNOWN and must never be equated with them.**

The private report carries a **separate assessment identity** in its key, so an ambiguous report
write cannot block re-assessment permanently. **The combined assessor requires** two distinct
execution identities, both locators `COMPLETE`, `publication_state_unknown = false` for both, the
same plan digest, the same inventory digest, the same source-schema version, exactly 48 planned
and 48 completed requests in each, matching subject-class and request inventories, **Run A ordered
before Run B**, and **at least eight calendar days between the accepted run dates**. It resolves
**both locator keys without listing**, retrieves **96 acquisition records and 96 payloads and zero
claims**, and verifies **every object's expected digest and byte count before parsing**. It
retrieves **no credential**, reaches **no provider**, performs **no S3 listing, delete, copy,
Bronze publication or CONTROL operation**, and writes **no local report**.

#### Two roles, and what each cannot do

**Two least-privilege roles and separate sessions**, so the separation is a property of the
identity system and not only of the code.

| | |
|---|---|
| **Acquisition role** | one governed secret retrieval · conditional `PutObject` to licensed `bronze/*` and to the locator prefix · metadata-only collision resolution. **No object-byte read**, no listing, no delete, no copy, no CONTROL, no bucket administration, no report publication |
| **Assessment role** | exact `GetObject` on the locator prefix and on referenced licensed Bronze objects · conditional report publication. **No credential or secret access, and no provider network access**, so it cannot make a provider request at all. No listing, no delete, no copy, no Bronze publication, no CONTROL, no bucket administration |
| **Deletion role** | **unchanged.** It can list and delete for deletion governance, and it **cannot read object bytes** |

A compromised acquisition path cannot exfiltrate the licensed store, and the assessment path
cannot contact a provider — so **a provider failure cannot be converted into an assessment
result**.

#### Parser, report and deletion

The parser and evaluator would live in a **new `data/qualify/sharadar/` package that
`data/ingest/` cannot import**, so the acquisition path stays parser-free; it **cannot import,
copy or adapt the public-test-key harness**, which stays untouched and **unauthorized to
execute**. Strict UTF-8 with **no replacement decoding**, RFC4180 handling, dataset-specific
schema contracts, **`Decimal` and never binary floating point**, real calendar-date parsing with
**no coercion of date-only values into instants**, duplicate detection, **delivered order observed
rather than silently reordered**, missing values distinct from zero, header-only responses valid
where appropriate, page-two completeness validation, an observed schema digest,
**`PROVIDER_REALISTIC_PIT` only with `PUBLIC_PIT` not expressible**, closed sanitized failures, and
**per-test compiled ceilings**.

The canonical private report lives **only** under `licensed/qualification/sharadar/reports/`,
carries classification, evidence identity, creation time, retention basis and deletion obligation,
**creates no routine local copy**, **never enters Git, CI, logs, chat, an AI session or CONTROL**,
and **contains no provider-selection recommendation**. **The combined report binds both executions
in fixed Run A / Run B order:**

```text
licensed/qualification/sharadar/reports/<run-a-execution-id>/<run-b-execution-id>/<assessment-id>.json
```

The accepted path grammar requires **three separately validated path segments**, **preserves
Run A / Run B order**, **forbids identical execution identities**, stays **LICENSED**, stays
**append-only and conditional**, is **never listed**, **never printed** and **never stored
locally**, is **never a cross-execution index**, **binds both locator identities and both evidence
sets**, and contains **no aggregate verdict, no provider-selection value, no readiness value and
no operational recommendation**. **One report is produced for the combined assessment**, and **no
preliminary Run A report is required by this architecture** — a separate Run A-only assessment
would be another ADR decision and another authorization, and is not introduced.

The deletion runbook gains a **clarification only**: `qualification/sharadar/locators/` and
`qualification/sharadar/reports/` are named as expected prefixes so their first appearance is not
recorded as a finding. **Deletion behaviour does not change** — no versioning, no Object Lock, no
replication, no archival lifecycle, no backup, prefix-wide deletion, separated deletion authority,
and the deletion role still cannot read. **A locator may be absent, and the deletion procedure
must never depend on one to discover licensed objects.**

#### What exists today

> **HISTORICAL — the state as of that merge, superseded by *The applied qualification
> infrastructure*.** The qualification Terraform has since been applied under a separate
> authorization and independently verified, so every existence, occurrence and deployment
> line below records that day and **no longer governs**. Its forward authorization
> boundaries are unchanged.

```text
ADR-0018:                                 ACCEPTED / IN FORCE -- PR #39 merged
clarification amendment:                  EFFECTIVE -- PR #42 merged, merge commit
                                          28239514b9e4e13f55ee98fa50877077e70bd593,
                                          approved clarification head
                                          579259a62ff7561ae2991f3923ea8aa1d0064be8;
                                          PROPOSED and without authority while that
                                          pull request was open
ADR-0018 architecture:                    ACCEPTED / IN FORCE
ADR-0018 offline implementation:          MERGED / DORMANT -- PR #41 merged, merge commit
                                          3ddd7d40741bb9a50ae4fc5452324ddbfb5e1ec0,
                                          approved implementation head
                                          96daac7963d936f231b37847579c5f28bb313760
fixed 48-request correction:              MERGED -- PR #44 merged, merge commit
                                          c945970613b80bfd4f42acc4f3acb4814895eb42,
                                          approved correction head
                                          78b4425077e65eeb12dfd24b35825741370e0e0f
offline implementation state              MERGED, DORMANT AND NEVER EXECUTED -- while PR #41
                                          was open it was an unmerged implementation
                                          candidate, and before PR #41 merged the offline
                                          package and its two dormant entry points were
                                          absent from main
implementation authorization              LATER, SEPARATE written authorizations, for
                                          offline construction, offline correction and
                                          offline validation only
ADR-0018 implementation execution:        NOT AUTHORIZED
infrastructure design and mutation:       NOT AUTHORIZED
infrastructure mutation:                  NOT AUTHORIZED
infrastructure deployment:                NOT AUTHORIZED / NOT PERFORMED
implementation execution:                 NOT AUTHORIZED / ZERO
Run A:                                    NOT AUTHORIZED / NOT RUN
Run B:                                    NOT AUTHORIZED / NOT RUN
assessment:                               NOT AUTHORIZED
combined assessment:                      NOT AUTHORIZED / NOT RUN
empirical-package executions              ZERO
provider requests by this package         ZERO
S3 operations by this package             ZERO
credential retrievals by this package     ZERO
P1-P9 executions by this package          ZERO
locators created by this package          ZERO
private reports created by this package   ZERO
new IAM roles created                     ZERO -- none exists
Terraform commands by this package        ZERO
licensed object-byte read surface         MERGED, DORMANT AND NOT DEPLOYED -- the bounded
                                          assessment-only read implementation now exists in
                                          committed code, it is dormant and not deployed, it
                                          permits no S3 listing, it is not a general read
                                          surface, and it has never been executed against
                                          licensed objects
retained evidence read by this package    no locator, record, payload or report has been read
                                          by the empirical package
acquisition direction                     the acquisition process remains write-only
ingestion isolation                       the ordinary ingestion path remains unable to use
                                          the qualification read surface
synthetic fixtures only                   YES -- no vendor row, no real security symbol
runtime-area listing incident:            RECORDED, SANITIZED -- filenames observed,
                                          NO file contents read, NOT reproduced by the
                                          review, NO tracked contamination found, and
                                          filenames intentionally NOT disclosed
further private-directory inspection:     NOT AUTHORIZED BY THAT INCIDENT
further incident diagnosis:               NOT AUTHORIZED BY THAT INCIDENT
```

**G1 OPEN · G2 OPEN · G3 CLOSED · G4–G7 OPEN**, ADR-0005 **PROPOSED**, INC-0002 **OPEN**, no
provider selected, Phase 3 **NOT COMPLETE**, CONTROL publication **DEFERRED**, live trading
**HARD-DISABLED**. A **third execution of the ADR-0017 entry point remains NOT AUTHORIZED**, and
**no live request of any kind is authorized by ADR-0018**.

### The infrastructure-feasibility gap, and ADR-0019 — ACCEPTED, and the merged correction

A read-only infrastructure-feasibility reconciliation of ADR-0018 against AWS's authorization
model returned the closed classification **STOPPED_ARCHITECTURE_GAP_HEAD_REQUIRES_GET**.
[ADR-0019](docs/decisions/ADR-0019-write-only-acquisition-collision-policy.md) records the
correction, and it has since merged. **ADR-0019: ACCEPTED / IN FORCE.**

**ADR-0019 architecture: ACCEPTED / IN FORCE**, by merge of **PR #46** at
**2026-09-01T01:01:22Z** — merge commit **`77974f476ead96548beb16543dfd3db8c03232c3`**, approved
ADR head **`bf0414c4a915d85a124ba400284ca1fa671fda27`**. **ADR-0019's conditional acceptance event
has occurred**, so the conditional status line it was written with has been satisfied.
**PR #46 was independently reviewed before its merge.**

**While PR #46 was open ADR-0019 was proposed and carried no authority**, and **ADR-0018's
original collision-resolution design and arithmetic governed before the PR #46 merge**. Those are
historical facts about those days, they stay true, and they are **not** rewritten as though the
amendment had authority before its merge. **ADR-0019 became effective only when the conditional
merge event occurred.**

**The merge approved architecture only, and authorized no production-code correction**, no
Terraform, no IAM, no infrastructure mutation, no deployment and no execution.

#### The ADR relationship, precisely

**ADR-0019 supersedes no ADR wholesale.** It **narrowly amends the enumerated clauses of
ADR-0018** — §4.5.3, §7.4, §9.1, §9.2, §9.3, §9.5 and §10.1, and nothing else. **ADR-0018 remains
ACCEPTED / IN FORCE except as amended by ADR-0019.** **ADR-0017 is not amended or superseded**,
**ADR-0011 is not amended or superseded**, and **the shared S3ResearchObjectStore remains
unchanged**. **ADR-0019's amendment is now authoritative architecture**, and **the production
implementation now conforms to that architecture offline** — the correction merged as PR #48.

#### The AWS constraint the amendment answers

```text
HeadObject requires the s3:GetObject permission
a GetObject for a known current object uses that same s3:GetObject permission
AWS exposes no independent s3:HeadObject IAM action
GetObjectAttributes also requires object-read authority
no condition key distinguishes the HTTP method -- S3 authorizes by action, never by verb
absence of s3:ListBucket prevents enumeration but not a known-key read
the current SSE-S3 design offers no KMS permission that could be withheld
an application protocol without a get_object method does not remove IAM authority
    from a compromised process
```

Sources: <https://docs.aws.amazon.com/AmazonS3/latest/API/API_HeadObject.html> ·
<https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-with-s3-policy-actions.html> ·
<https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObjectAttributes.html>

#### The authoritative acquisition architecture

**These are architecture requirements, not implementation facts.** The IAM-preserving acquisition
zero-HEAD fail-closed design is what now governs:

| | |
|---|---|
| **the acquisition role receives no s3:GetObject** | and **no s3:GetObjectVersion**, **no s3:GetObjectAttributes**, and no listing, copy, delete or CONTROL authority |
| **the acquisition publication surface has no head_object** | and **no get_object**, no general read, no listing, no copy and no delete |
| **acquisition HeadObject: exactly 0** | **acquisition GetObject: exactly 0** |
| **every acquisition-side conditional PutObject collision fails closed** | no occupied object is inspected, compared, classified identical, adopted or resumed from |
| **a 412 does not establish that the occupied object is identical** | **BRONZE_NAME_OCCUPIED is the authoritative architectural closed outcome** |
| **LOCATOR_NAME_OCCUPIED is the authoritative architectural replacement for the earlier collision claim** | it asserts only that the name was occupied and the occupying content was not determined |
| **a partial locator cannot claim the collided object was verified or retained** | if a truthful locator cannot be published, the closed result remains **LOCATOR_NOT_PUBLISHED** |
| **both the IAM boundary and the application boundary are retained** | independently — neither is a substitute for the other |

**The application-only alternative is not adopted.** Granting the read action would let a
compromised credential-holding process read known licensed objects, invalidating ADR-0018 §10.3's
identity-system compromise argument.

**The later implementation correction must introduce an ADR-0018-specific write-only publication
surface** — conditional put only, no head_object, no get_object, unreachable from ADR-0017, and
structurally prevented from importing or invoking the assessment read surface. **That requirement
has since been satisfied offline by the correction merged as PR #48**, and it stays a standing
architecture requirement rather than a one-off a later edit could undo.

#### The implementation gap — closed offline, and stated plainly

> **HISTORICAL — the state as of that merge, superseded by *The applied qualification
> infrastructure*.** The qualification Terraform has since been applied under a separate
> authorization and independently verified, so every existence, occurrence and deployment
> line below records that day and **no longer governs**. Its forward authorization
> boundaries are unchanged.

**The architecture is accepted. The code has been corrected, offline.** These are separate states
and they are not collapsed:

| Layer | Current status |
|---|---|
| Architecture | **ADR-0019 accepted and effective** |
| Existing code | **merged, dormant, offline-conforming** |
| Corrective code | **merged — PR #48** |
| Terraform / IAM | **not authorized, not implemented** |
| Deployment | **not authorized, not performed** |
| Execution | **ZERO** |

```text
ADR-0019 architecture:                    ACCEPTED / IN FORCE
ADR-0018 offline implementation:          MERGED / DORMANT
ADR-0019 production-code correction:      MERGED / DORMANT / OFFLINE-CONFORMING
PR #48 merge commit:                      f0b39fccdfb36ea69d08fb4def3979b87814b9ff
approved implementation head:             64dc3388f402ee98cf8940d94b42fa16aa7553e2
implementation-correction prerequisite:   SATISFIED
```

**PR #48 merged**, and with it **the production implementation now conforms to that architecture
offline**. **The dormant acquisition implementation no longer uses the pre-ADR-0019 shared
collision path**, which issued a conditional HeadObject after a 412; **the ADR-0018-specific
write-only publication surface now exists**, conditional-put only, with no `head_object` and no
`get_object` in its shape; and **the merged dormant acquisition implementation has zero
acquisition HeadObject and zero acquisition GetObject**. **The current dormant implementation is
offline-conforming under the authoritative architecture.**

**Before PR #48 merged the production implementation did not yet conform**, the dormant
acquisition path still used the shared collision path, and no ADR-0018-specific write-only
publication surface existed — historical facts about those days that stay true and are **not**
rewritten as though the correction had always been there.

**The three status lines those days carried are kept verbatim, and none of them is current.**
Each is written with the event that ended it, so it reads as of then rather than as of now:
**before PR #48 merged, infrastructure design: BLOCKED pending implementation correction**;
**before PR #48 merged, production implementation correction: NOT AUTHORIZED / NOT IMPLEMENTED**;
**before PR #48 merged, the production implementation does not yet conform to that architecture**.
They are kept rather than deleted, because a status document that erases the state it moved out of
cannot show that it moved — and **none of them may be restated as a current claim**.

**The ADR-0019 implementation-correction prerequisite is SATISFIED**, and that is the whole of
what it does. **Satisfying the implementation prerequisite does not itself authorize or begin
infrastructure work**: **infrastructure design and mutation: NOT AUTHORIZED / NOT IMPLEMENTED**,
**Terraform / IAM: NOT AUTHORIZED / NOT IMPLEMENTED**, **deployment: NOT PERFORMED** and
**execution: ZERO**. **Offline-conforming is not deployed, not active, not operational, not
authorized to run and not empirically validated** — the implementation is code located in
production source, and **the next possible gate is a separate owner authorization for offline
infrastructure, Terraform and IAM preparation**.

#### The current architectural arithmetic

**This is the governing acquisition arithmetic now.**

```text
provider requests per successful run          exactly 48
Bronze conditional PutObject                  exactly 144
locator PutObject                             1 to 3
acquisition PutObject: 145 to 147
acquisition HeadObject: exactly 0
acquisition GetObject: exactly 0
successful-run acquisition S3 operations: 145 to 147
two successful runs: 290 to 294
assessment: unchanged at 195 to 196
whole successful package: 485 to 490
```

Current deadline formulas, with `D = 1800 seconds`:

```text
locator terminal reserve      L >= 3 * T_s3 + C
per-request S3 obligation     3 * T_s3
feasibility                   T_req + P + 3 * T_s3 + L <= D
admission                     remaining >= T_req + 3 * T_s3 + L
```

**Preserved unchanged:** partial and refused runs are never reported as having performed 145
operations; the 48-request maximum; the monotonic clock; zero provider retries; disabled SDK
automatic retries; bounded socket timeouts; Run A and Run B separation; the assessment
arithmetic; and the P1–P9 ceilings.

<!-- RETIRED-ARITHMETIC BEGIN: ADR-0018 original, superseded by ADR-0019, no longer governing -->

**The superseded acquisition figures are ADR-0018's original accepted arithmetic and no longer
govern.** ADR-0018's `zero to 145` conditional HeadObject range, its `145 to 290` and `147 to 292`
per-run totals, its `294 to 584` two-run total, its `485 to 780` package envelope, its `6 * T_s3`
per-request collision allowance and its `4 * T_s3` locator allowance are recorded as **history and
as an explanation of what ADR-0019 amended**, and are **not** current governing status. ADR-0018's
own text is unchanged and is not rewritten.

<!-- RETIRED-ARITHMETIC END -->

#### What stays closed

> **HISTORICAL — the state as of that merge, superseded by *The applied qualification
> infrastructure*.** The qualification Terraform has since been applied under a separate
> authorization and independently verified, so every existence, occurrence and deployment
> line below records that day and **no longer governs**. Its forward authorization
> boundaries are unchanged.

```text
implementation-correction prerequisite:   SATISFIED -- PR #48 merged
infrastructure design and mutation:       NOT AUTHORIZED / NOT IMPLEMENTED
production implementation correction:     MERGED / DORMANT / OFFLINE-CONFORMING
Terraform/IAM implementation:             NOT AUTHORIZED / NOT IMPLEMENTED
infrastructure mutation:                  NOT AUTHORIZED / NOT PERFORMED
deployment:                               NOT AUTHORIZED / NOT PERFORMED
Run A:                                    NOT AUTHORIZED / NOT RUN
Run B:                                    NOT AUTHORIZED / NOT RUN
combined assessment:                      NOT AUTHORIZED / NOT RUN
empirical-package executions              ZERO
new qualification IAM roles               ZERO -- none exists
G1                                        OPEN
G2                                        OPEN
provider selected                         NONE
Phase 3                                   NOT COMPLETE
CONTROL publication                       DEFERRED
live trading                              HARD-DISABLED
a third ADR-0017 authenticated attempt    NOT AUTHORIZED
```

**Acceptance of ADR-0019 is not authorization to implement or execute it.**

**No infrastructure was built and no run occurred before the discovery.** The AWS
HeadObject/s3:GetObject conflict was **discovered after ADR-0018's dormant implementation had
merged**; infrastructure deployment was never authorized, no qualification IAM role was ever
created, and Run A, Run B and the combined assessment have never run. **None of that changed when
the correction merged**: PR #48 was an offline implementation correction, and **no infrastructure
was built, no IAM role was created, no AWS or provider request was made and no run occurred by
it**.


### The completed Run A empirical acquisition — COMPLETED, and what it does and does not establish

**Run A ran once, on 4 September 2026, and it finished.** The ADR-0018 / ADR-0019 / ADR-0020
empirical acquisition implementation — merged, dormant and unexecuted until that day — was
run once under its own separate written authorization. **Run A completed with exit code `0`**,
and its closed public outcome was `empirical acquisition completed`.

**This section governs the current state.** The repository's binding-correction history records the
days those pull requests merged, the operator-access section below records the day of the
materialization, and every per-merge section beneath it records its own merge. Their Run A,
execution, materialization and activity lines describe their own dates and **no longer govern**,
while their forward authorization boundaries are unchanged. **No ADR document and no historical
review report is rewritten by this synchronization.**

#### What Run A established

**One entry-point invocation, and the accounting the architecture was built to produce.** Every
figure below is the observed count of that one execution, and each sits inside the band ADR-0019's
governing arithmetic admits for one successful acquisition run.

| | |
|---|---|
| **the run** | one entry-point invocation · exit code `0` · closed public outcome `empirical acquisition completed` |
| **the provider** | **exactly 48 sequential provider requests**, and **zero provider retries** |
| **the writes** | **exactly 145 append-only licensed-S3 writes** — 144 Bronze publications and one locator, inside ADR-0019's admitted 145-to-147 band |
| **the reads** | **zero object-byte `GetObject`**, **zero conditional `HeadObject`** and **zero listing operations**, so acquisition stayed write-only exactly as ADR-0019 requires |
| **CONTROL** | **zero CONTROL operations** |
| **the credential** | **one** `GetSecretValue`, with no credential, fragment, digest, fingerprint or measurement recorded anywhere |
| **Terraform** | **zero Terraform operations** — the ADR-0023 correction held, and the acquisition actor attempted no state read |
| **identity** | **two** `sts:GetCallerIdentity` invocations in total — one external identity precheck, and the entry point's own internal identity gate |
| **the locator** | **published last**, and **addressable** |
| **the objects** | **145 objects newly written** under the append-only collision policy |
| **the execution identity** | one execution identifier allocated and **permanently retired**, with an owner-only private allocation receipt |
| **the private inputs** | the environment binding, the runtime binding, the applied secret-access evidence and the private Terraform input each **unchanged** |
| **the repository** | **no repository mutation occurred during Run A** |

**Nothing private is recorded here, and none of it is needed to state what happened.** No execution
identifier or recoverable portion of one appears in this repository, and neither does an
allocation-receipt path or filename, an account id, an ARN, a bucket name, an object key, a secret
identifier, a credential or token, a user-specific filesystem path, a subject, ticker or provider
payload, a private digest, or a private P1–P9 result.

#### What Run A did not establish

**A completed command is an operational outcome, and it is not a provider verdict.** Every
distinction below is load-bearing rather than decorative.

| | |
|---|---|
| **a completed acquisition is not a finding** | **P1–P9 remain unevaluated by the combined assessment**, which is the only thing that evaluates them, and it runs after Run B |
| **retrieved bytes are not correct bytes** | Run A establishes **no data correctness and no data quality** |
| **one answered inventory is not an entitlement** | **provider-wide entitlement stays UNKNOWN**, and so does **subscription-wide entitlement** |
| **an acquisition is not a selection** | **no provider is selected**, and **G1 and G2 stay OPEN** |
| **a completed run is not a phase** | **Phase 3 stays NOT COMPLETE**, and **production ingestion, backfill and update stay unauthorized** |
| **operational readiness is not trading readiness** | **CONTROL stays DEFERRED**, **live trading stays HARD-DISABLED**, and **backtesting has not started** |

**Run A is spent, and it cannot be repeated.** Its execution identifier is **permanently retired**,
so the append-only store would refuse a repeat, and **a Run A retry is not authorized**. **Run B is
a separate second acquisition that requires its own written authorization and has not run.** It
must fall **at least eight calendar days after Run A**, and the **earliest approved scheduling
target is 12 September 2026**. **The combined assessment runs only after Run B, under another
authorization.**

#### Run A status

```text
Run A:                                            COMPLETED / 4 SEPTEMBER 2026
Run A entry-point invocations:                    1
Run A exit code:                                  0
Run A closed public outcome:                      empirical acquisition completed
provider requests:                                48
provider retries:                                 0
licensed-S3 PutObject:                            145
conditional HeadObject:                           0
object-byte GetObject:                            0
listing operations:                               0
CONTROL operations:                               0
total S3 operations:                              145
credential retrievals (GetSecretValue):           1
Terraform operations:                             0
STS GetCallerIdentity invocations:                2
locator:                                          PUBLISHED LAST / ADDRESSABLE
newly written objects:                            145
execution identifier:                             ALLOCATED AND PERMANENTLY RETIRED
private inputs:                                   UNCHANGED
repository mutation during Run A:                 NONE
a Run A retry:                                    NOT AUTHORIZED / NOT RUN
Run B:                                            NOT AUTHORIZED / NOT RUN
Run B minimum separation:                         AT LEAST 8 CALENDAR DAYS AFTER RUN A
Run B earliest approved target:                   12 SEPTEMBER 2026
combined assessment:                              NOT AUTHORIZED / NOT RUN
P1-P9:                                            UNEVALUATED
data correctness and quality:                     NOT ESTABLISHED
provider-wide entitlement:                        UNKNOWN
subscription-wide entitlement:                    UNKNOWN
production ingestion/backfill/update:             NOT AUTHORIZED / NOT RUN
third ADR-0017 acquisition:                       NOT AUTHORIZED / NOT RUN
sixth private-binding preflight:                  NOT AUTHORIZED / NOT RUN
further infrastructure mutation:                  NOT AUTHORIZED
backtesting:                                      NOT STARTED
G1 / G2:                                          OPEN / OPEN
provider selected:                                NONE
Phase 3:                                          NOT COMPLETE
CONTROL:                                          DEFERRED
live trading:                                     HARD-DISABLED
```

**A completed acquisition authorizes no further run.** Completing Run A **opened none of the other
gates**: a Run A retry, Run B, the combined assessment, a third ADR-0017 acquisition, a sixth
private-binding preflight, further infrastructure mutation and production ingestion each remain a
separate written authorization, and **acceptance, implementation, deployment, access and execution
stay distinct gates that are never collapsed into one**.

### The Strategy Brain specification — ACCEPTED ON MERGE, and nothing is implemented

**The Brain is specified. The Brain does not exist.** Those are two facts, and they are kept apart:
a reviewable specification now sits in the repository at
[`docs/phase4/strategy-brain-specification.md`](docs/phase4/strategy-brain-specification.md), and
**no Brain runtime module, strategy module, factor calculation, scanner, AI agent, portfolio sizing
or order routing has been written or authorized**.

**[ADR-0026](docs/decisions/ADR-0026-strategy-brain-architecture-and-governance.md) is ACCEPTED — EFFECTIVE
ONLY ON THE INDEPENDENT REVIEW AND MERGE OF PR #70, and until that merge it is PROPOSED and
carries no authority.** On that merge it becomes
**ACCEPTED / IN FORCE** as **architecture, contracts, governance and future implementation
boundaries** — and **nothing more**. That it carries no authority today is a statement about these
days; it stays true of them after any later merge, and it is **not** rewritten as though the
decision had authority before it was accepted.

**It amends and supersedes no ADR.** It **refines
[ADR-0006](docs/decisions/ADR-0006-adopt-blueprint-v3-and-strategy-brain-governance.md) §D and §E
into checkable contracts**, references
[ADR-0004](docs/decisions/ADR-0004-deterministic-order-identity-idempotency-and-execution-lifecycle.md)
rather than changing it, and leaves ADR-0005 **PROPOSED**.

**The locked boundary, expressed as a contract.** The Brain produces **no broker order and no
position size**; its terminal output is a deterministic typed `CandidateIntent`, which **may never**
carry shares, a dollar amount, a final position size, a final broker order type, a broker route, a
client order ID, a broker order ID, a credential, an account number or an arbitrary free-form
execution instruction. **The exclusion is structural, not conventional** — no field of those
meanings, no free-text field an instruction could arrive through, and no extension point that admits
one. The **technical stop is a reference to an invalidation level, not an order**.

**`READY_FOR_RISK_REVIEW` is not an approval to trade**; it records the absence of a deterministic
objection, and portfolio and risk decide independently. `MAYBE`, `BUY`, `SELL`, `EXECUTE` and
`APPROVED_ORDER` are **refused by name**.

**A deterministic failure cannot be rescued by AI.** AI may **remove** a candidate; it may never
**restore** one. The Research Agent consumes **only already shortlisted candidates** — an AI that
may choose what to look at is a scanner, and the scanner is deterministic by design.

**Short alpha is asymmetric.** **No generic "Breakdown Short" is authorized**, a short module **may
not be produced by inverting a long breakout**, and **bottom-decile momentum alone is not short
authorization**. `BLOCKED_BORROW` is a first-class state, borrow is **never inferred from price
behaviour**, and the live pre-submit borrow recheck belongs to execution and risk.

**Self-maturing is not self-governing**, exactly as ADR-0006 §C holds. Automation may monitor,
research, generate hypotheses, operate shadow challengers, prepare governance packets, reduce or
disable new entries under preapproved rules, and fail closed. **It may never** promote a strategy
into order-producing Paper or live operation, replace a production strategy or model, change
production parameters, increase capital, risk, leverage or short exposure, purchase a licence, add a
provider, resume a governed suspension, or bypass the kill switch.

**No alpha is claimed anywhere.** The specification does not claim that Breakout, Pullback, PEAD or
Deterioration Short works, that AI adds alpha, that residual momentum is superior or that an options
overlay helps. Its experiment matrix is a list of **unanswered questions**, and **none has been
run**.

```text
Brain specification:                              ACCEPTED EFFECTIVE ON MERGE OF PR #70
Brain runtime implementation:                     NOT STARTED / NOT AUTHORIZED
core strategy runtime implementation:             NOT STARTED / NOT AUTHORIZED
factor, scanner and AI-agent implementation:      NOT STARTED / NOT AUTHORIZED
portfolio and risk engine implementation:         NOT STARTED / NOT AUTHORIZED
new src/ modules created by this specification:   NONE
backtesting:                                      NOT STARTED
provider data used by this specification:         NONE
private artifacts read:                           NONE
AWS / Terraform operations:                       NONE
broker activity:                                  NONE
Run A retry:                                      NOT AUTHORIZED / NOT RUN
Run B:                                            NOT RUN / NOT AUTHORIZED
Run B earliest approved target:                   12 SEPTEMBER 2026
combined assessment:                              NOT RUN / NOT AUTHORIZED
P1-P9:                                            UNEVALUATED
data correctness and quality:                     NOT ESTABLISHED
G1 / G2:                                          OPEN / OPEN
provider selected:                                NONE
Phase 3:                                          NOT COMPLETE
CONTROL:                                          DEFERRED
live trading:                                     HARD-DISABLED
```

**"Brain started" does not mean runtime coding started.** **Specification, implementation, research,
deployment and execution are five separate gates**, and they are never collapsed into one.

### The Cockpit and Feedback specification — ACCEPTED ON MERGE, and nothing is implemented

**The Cockpit is specified. The Cockpit does not exist.** Those are two facts, and they are kept
apart: a reviewable specification package now sits in the repository, and **no Cockpit application,
read API, projection runtime, metric engine, feedback automation, database, migration or scheduler
has been written or authorized**.

**[ADR-0027](docs/decisions/ADR-0027-cockpit-and-feedback-architecture-and-governance.md) is
ACCEPTED — EFFECTIVE ONLY ON THE INDEPENDENT REVIEW AND MERGE OF PR #71, and until that merge it
is PROPOSED and carries no authority.** On that merge it becomes **ACCEPTED / IN FORCE** as
**architecture, contracts, governance and future implementation boundaries** — and **nothing more**.
That it carries no authority today is a statement about these days; it stays true of them after any
later merge, and it is **not** rewritten as though the decision had authority before it was accepted.

**It amends and supersedes no ADR.** It consumes
[ADR-0026](docs/decisions/ADR-0026-strategy-brain-architecture-and-governance.md) — **ACCEPTED / IN
FORCE** through the merge of PR #70 — unchanged, applies
[ADR-0006](docs/decisions/ADR-0006-adopt-blueprint-v3-and-strategy-brain-governance.md)'s authority
split rather than altering it, and leaves ADR-0005 **PROPOSED**.

**The specification package.**

| Document | What it governs |
|---|---|
| [`docs/architecture/COCKPIT_FEEDBACK_EXTENSION.md`](docs/architecture/COCKPIT_FEEDBACK_EXTENSION.md) | the Blueprint V3.0 architecture extension — subsystem position, data flow, boundaries, vocabularies |
| [`docs/cockpit/cockpit-v1-specification.md`](docs/cockpit/cockpit-v1-specification.md) | the 36 Cockpit V1 product areas and their functional contracts |
| [`docs/cockpit/read-model-contracts.md`](docs/cockpit/read-model-contracts.md) | envelopes, read-model contracts, the endpoint catalog and the metric dictionary |
| [`docs/cockpit/feedback-self-maturation-specification.md`](docs/cockpit/feedback-self-maturation-specification.md) | the feedback loop, its stage contracts and its authority matrix |
| [`docs/cockpit/ui-ux-specification.md`](docs/cockpit/ui-ux-specification.md) | presentation, interaction and observable UI acceptance |
| [`docs/cockpit/traceability-matrix.md`](docs/cockpit/traceability-matrix.md) | all 36 areas traced, plus the C1–C10 delivery sequencing |

**The adopted Blueprint V3.0 PDF does not describe the Cockpit, and it is not edited.** The
extension is tracked Markdown indexed beside the immutable adopted document, exactly as the
Document Control override is. **No claim is made that the adopted PDF already contains this
material.**

**V1 is observational, and READ-ONLY is defined by absence.** No Cockpit endpoint, command,
assistant tool, hidden handler, background job or scheduled action may place or cancel an order,
change a stop, change risk or capital, activate or promote a strategy, enable leverage, change the
provider, execute Run B or an assessment, publish CONTROL, alter production strategy state, or
approve or reject a governance release. **Governance screens display recorded decisions and packets;
they do not originate authoritative approval records in V1.** Every future control is **inert** —
explicitly unavailable, **with no executable handler and no control API route**.

**The read-model boundary applies to the backend as well as the browser.** Facts and events become
projections, projections become a versioned read API, and the interface consumes that and nothing
else. The Cockpit reaches **no provider API, no provider or AWS credential, no brokerage API or
credential, no mutable Brain internal and no private qualification artifact**, and **an API proxy
must not become a disguised provider or broker integration**.

**The ownership split is preserved exactly.** Brain → `CandidateIntent` only; portfolio and risk →
ownership permission, sizing, shares and risk constraints; execution → order type, route, fills,
protection and reconciliation. **No sizing or execution field is added to `CandidateIntent` to
simplify a screen** — Trade Detail joins separately owned downstream facts by **safe internal
references**. **The Brain status vocabulary is not extended with downstream states.**

**Five maturity stages map onto existing vocabularies and replace none of them.** `RESEARCH`,
`SHADOW`, `AUTOMATED_PAPER`, `MICRO_LIVE` and `SCALED_LIVE` present ADR-0026 lifecycle values over
the unchanged runtime `Environment` enum. **Shadow has no order authority**, **Automated Paper stays
the first order-producing stage and requires human approval**, and **selecting an environment in the
interface advances no maturity**.

**Availability is typed, and a missing value is never a zero.** `AVAILABLE`, `NOT_YET_AVAILABLE`,
`NOT_IMPLEMENTED`, `NOT_AUTHORIZED`, `UNEVALUATED`, `STALE`, `PARTIAL`, `ERROR`, `NOT_APPLICABLE`,
`EMPTY_VERIFIED` and `INSUFFICIENT_OBSERVATIONS` are distinct states, and **none is rendered as
zero, healthy, passed or no incidents**. **SYNTHETIC/DEMO is provenance, not an environment**, and
**a historical success carries its as-of time**.

**"Read model" and "derived" do not mean safe to publish.** `PUBLIC_SAFE` may be hosted externally;
`PRIVATE_OPERATIONAL` and `LICENSED_DERIVED` stay inside the approved private boundary;
`UNCLASSIFIED` **fails closed**; and `CONTROL` is **refused at admission** with CONTROL publication
still **DEFERRED**. **A server-side render, an API proxy, an edge cache and a build-time fetch are
each a copy**, and none may silently receive a licensed payload. **Licensed content is never copied
into an immutable audit payload** — audit events carry classified references, and deletion uses
authorized tombstone semantics that keep the governance evidence and retain no vendor data.

**Self-maturing is not self-governing.** Automation may monitor, diagnose, detect drift and failure
clusters, preregister and run authorized-scope research, operate authorized shadow Challengers,
prepare governance packets and fail closed. **It may never** promote into order-producing Paper or
live operation, replace a production model or parameter, increase capital, risk, leverage or short
exposure, buy a licence, add a provider, resume a governed suspension, or change kill-switch
behaviour. **Preregistration is immutable and results append**; **all trials count, including failed
and abandoned runs**; **no production parameter mutates automatically**; and **no numerical threshold
becomes a production rule because it appeared in a synthetic example**.

**The stack is decided and nothing is deployed.** Next.js App Router, TypeScript, Tailwind,
shadcn/ui on Radix, TanStack Query and Table, Zod and Zustand where justified; Recharts,
TradingView Lightweight Charts and selective Apache ECharts; FastAPI and Pydantic; PostgreSQL for
operational projections and DuckDB with Parquet for qualified heavy research later; Vercel
acceptable for an eligible Next.js deployment with Python services separately containerized. **No
version is pinned**, **no dependency is installed**, **nothing is deployed** and **no spending is
authorized**. **LEAN remains the research and execution engine**, and **no claim is made about the
Atlas or SIRE internal technology stack** — the visual benchmark is owner-supplied direction, no
retrieval was performed in this cycle, and a coordinator retrieval returned 404.

**All 36 areas stay in V1 scope and are traced**, including **area 36**, which keeps four concepts
apart: **Trade History** is the trade ledger, **Trade Detail** is the complete story of one trade,
**Execution History** is order and fill mechanics, and the **Audit Trail** is immutable forensic
events. **A fill is never counted as a separate trade**, **a partial exit reduces a trade rather
than closing it**, **a missing event is never inferred**, and **the owner's manual activity is never
adopted as platform evidence**.

**No alpha is claimed anywhere.** No screen, metric or example asserts that any strategy works, and
**no performance figure in the package is a result**.

```text
Cockpit specification:                            ACCEPTED EFFECTIVE ON MERGE OF PR #71
Cockpit application implementation:               NOT STARTED / NOT AUTHORIZED
read-model, projection and API implementation:    NOT STARTED / NOT AUTHORIZED
feedback and learning-engine implementation:      NOT STARTED / NOT AUTHORIZED
Brain runtime implementation:                     NOT STARTED / NOT AUTHORIZED
portfolio and risk engine implementation:         NOT STARTED / NOT AUTHORIZED
database, migration, scheduler and deployment:    NOT STARTED / NOT AUTHORIZED
new src/ modules created by this specification:   NONE
dependency or manifest changes:                   NONE
Blueprint PDF changes:                            NONE
backtesting:                                      NOT STARTED
provider data used by this specification:         NONE
private artifacts read:                           NONE
AWS / Terraform operations:                       NONE
broker activity:                                  NONE
Run A retry:                                      NOT AUTHORIZED / NOT RUN
Run B:                                            NOT RUN / NOT AUTHORIZED
Run B earliest approved target:                   12 SEPTEMBER 2026
Run A to Run B separation:                        AT LEAST 8 CALENDAR DAYS
combined assessment:                              NOT RUN / NOT AUTHORIZED
P1-P9:                                            UNEVALUATED
data correctness and quality:                     NOT ESTABLISHED
G1 / G2:                                          OPEN / OPEN
provider selected:                                NONE
Phase 3:                                          NOT COMPLETE
CONTROL:                                          DEFERRED
live trading:                                     HARD-DISABLED
```

**"Cockpit specified" does not mean Cockpit implementation started.** **Specification,
implementation, research, deployment and execution are five separate gates**, and they are never
collapsed into one.

### The qualified operator access — MATERIALIZED, INDEPENDENTLY VERIFIED, and not authorized to use

**One owner-approved human operator now holds the governed qualification access, both governed AWS
profiles are materialized, and an independent review confirmed each identity preflight.** The
principals applied under PR #60 are no longer capability without a holder: a person can reach them,
and a review that did not perform the materialization confirmed that they do.

**The completed Run A empirical acquisition above governs the current state.** This section records
the materialization, and its Run A, execution and activity lines now carry a historical banner. The
applied-infrastructure section below records the day of the apply, and its operator-group, profile
and membership-gate lines carry their own; every per-merge section beneath it carries its own. Their
existence, occurrence, membership and deployment lines describe their own dates and no longer
govern, while their forward authorization boundaries are unchanged. **No ADR document and no
historical review report is rewritten by this synchronization.**

**Who the operator is stays out of this repository.** The group holds **exactly one owner-approved
human member**, and that is the whole of what is recorded here: **no name, user name, email address,
identity-store or group identifier, membership identifier, role suffix, generated role name,
account id, ARN, SSO start URL, fingerprint, artifact filename or artifact digest appears in this
repository**, and none of it is needed to state what exists.

#### What the materialization established

**The operator was selected by the owner**, the membership and both governed profiles were
materialized under their own separate authorization, and **an independent review read the result
rather than producing it**.

```text
qualification infrastructure:                     APPLIED / INDEPENDENTLY VERIFIED
operator selection:                               OWNER-APPROVED
operator group:                                   EXACTLY 1 OWNER-APPROVED HUMAN MEMBER / ASSIGNED
operator membership:                              MATERIALIZED / INDEPENDENTLY VERIFIED
governed acquisition profile:                     MATERIALIZED / IDENTITY PREFLIGHT PASSED
governed assessment profile:                      MATERIALIZED / IDENTITY PREFLIGHT PASSED
profile crossover:                                NONE
AWS config ACL:                                   EFFECTIVE ACCESS PRESERVED
membership/profile gate:                          COMPLETED
```

**Each profile answers for itself, and neither answers for the other.** The acquisition profile's
identity preflight passed as the acquisition actor, the assessment profile's passed as the
assessment actor, and **profile crossover is NONE** — neither profile resolved to the other's
permission-set role. That separation is the property ADR-0021 chose and ADR-0022 renamed, and it is
now observed rather than only declared.

**The AWS configuration remained readable to its owner.** The materialization left the local AWS
configuration's **effective access preserved**, so the governed profiles are usable by the operator
they were created for and by nobody this repository knows of.

#### What the materialization did not establish

**Materialized access is not authority to use it.** A person can now reach the governed roles;
nothing has been run with them, and every distinction below is load-bearing rather than decorative.

| | |
|---|---|
| **a materialized profile is not a qualification run** | **no qualification execution, no binding preflight, no provider acquisition, no Run A, no Run B and no combined assessment has happened**, and each stays a separate written authorization |
| **an identity preflight is not a provider credential** | **no provider credential was retrieved by this transition**, and **whether the stored secret authenticates against Sharadar stays UNKNOWN** |
| **reaching a role is not using it** | **no S3 object operation and no provider request occurred**, so the licensed store is untouched by this transition |
| **completing this gate opened no other** | the membership and profile gate is **COMPLETED**; the **sixth private-binding preflight**, a **third ADR-0017 acquisition**, **Run A**, **Run B** and the **combined assessment** each stay **NOT AUTHORIZED / NOT RUN** |
| **operator access is not provider selection** | **no provider is selected**, **G1 and G2 stay OPEN**, and **Sharadar is neither finally qualified nor chosen** |
| **qualified access is not Phase 3** | **no acquisition has succeeded**, **no backtest has begun**, **Phase 3 is NOT COMPLETE**, **CONTROL stays DEFERRED** and **live trading stays HARD-DISABLED** |

#### Qualified operator status

> **HISTORICAL — the state as of that materialization, superseded by *The completed Run A
> empirical acquisition*.** Run A has since been run once under a separate authorization, so every
> Run A, execution and activity line below records that day and **no longer governs**. Its forward
> authorization boundaries are unchanged.

```text
qualification infrastructure:                     APPLIED / INDEPENDENTLY VERIFIED
operator selection:                               OWNER-APPROVED
operator group:                                   EXACTLY 1 OWNER-APPROVED HUMAN MEMBER / ASSIGNED
operator membership:                              MATERIALIZED / INDEPENDENTLY VERIFIED
governed acquisition profile:                     MATERIALIZED / IDENTITY PREFLIGHT PASSED
governed assessment profile:                      MATERIALIZED / IDENTITY PREFLIGHT PASSED
profile crossover:                                NONE
AWS config ACL:                                   EFFECTIVE ACCESS PRESERVED
membership/profile gate:                          COMPLETED
sixth private-binding preflight:                  NOT AUTHORIZED / NOT RUN
provider credential retrieval:                    NONE
S3/provider activity:                             NONE
qualification execution:                          NOT AUTHORIZED / NOT RUN
third ADR-0017 acquisition:                       NOT AUTHORIZED / NOT RUN
Run A:                                            NOT AUTHORIZED / NOT RUN
Run B:                                            NOT AUTHORIZED / NOT RUN
combined assessment:                              NOT AUTHORIZED / NOT RUN
further infrastructure mutation:                  NOT AUTHORIZED
backtesting:                                      NOT STARTED
G1 / G2:                                          OPEN / OPEN
provider selected:                                NONE
Phase 3:                                          NOT COMPLETE
CONTROL:                                          DEFERRED
live trading:                                     HARD-DISABLED
```

**A materialized access path authorizes no run.** Completing the membership and profile gate
**opened none of the others**: the sixth private-binding preflight, qualification execution, a third
ADR-0017 acquisition, Run A, Run B and the combined assessment each remain a separate written
authorization, and **acceptance, implementation, deployment, access and execution stay distinct
gates that are never collapsed into one**.

### The applied qualification infrastructure — APPLIED, INDEPENDENTLY VERIFIED, and not authorized to use

**PR #60 is merged, the controlled saved-plan apply is complete, and an independent post-apply
verification passed.** The qualification principals this repository has declared since PR #56 are
no longer declarations alone: the governed objects exist in the target account, and a review that
did not perform the apply confirmed them there.

**This section records the apply, and its operator-group, profile and membership-gate lines are
superseded by *The qualified operator access* above.** Every per-merge section below records what
was true on its own merge date and now carries a historical banner: its existence, occurrence and
deployment lines describe that day and no longer govern, while its forward authorization
boundaries are unchanged. **No ADR document and no historical review report is rewritten by this
synchronization.**

#### What the apply established

**The apply ran from a saved plan under its own separate authorization**, and **the independent
verification read the result rather than producing it**. The Terraform state advanced by exactly
one serial with its lineage unchanged, and each governed object was observed:

```text
live customer-managed IAM policies:               2 VERIFIED
live Identity Center permission sets:             2 VERIFIED
live customer-managed-policy references:          2 VERIFIED
live account assignments:                         2 VERIFIED
generated Identity Center runtime roles:          2 VERIFIED
role trust policies:                              VERIFIED
IAM identity-policy simulation:                   PASSED
```

**The generated runtime roles are Identity Center's, not this repository's.** It still authors no
`aws_iam_role`, no trust policy, no IAM user, no access key and no `sts:AssumeRole`: each
assignment causes Identity Center to create and own the role it produces. **No account id, ARN,
identity-store or group identifier, role suffix, generated role name, bucket name or state key is
recorded here**, and none is needed to state what exists.

#### What the apply did not establish

> **HISTORICAL — the state as of that apply, superseded by *The qualified operator
> access*.** The operator-group, profile and membership-gate lines below record the day of
> the apply and **no longer govern**. Its forward authorization boundaries are unchanged.

**Infrastructure existence is not qualification success.** The resources exist; nothing has used
them, and every distinction below is load-bearing rather than decorative.

| | |
|---|---|
| **an assigned empty group is not human access** | the governed operator group **is assigned and remains empty**, with **no human members** — so **no person currently holds qualification access** |
| **an IAM simulation is not a login** | the identity-policy simulation **passed as a policy evaluation**. **No governed SSO login has been performed or proven**, and **no end-to-end authorization is established** |
| **applied resources are not permission to operate them** | the apply created capability, **not authority to use it**. Every downstream gate stays closed |
| **eligibility is not execution** | adding an operator to the group and materializing a governed profile are now **possible**; **neither has been done**, and each is **separately authorized** |
| **acquisition eligibility is not provider selection** | **no provider is selected**, **G1 and G2 stay OPEN**, and **Sharadar is neither finally qualified nor chosen** |
| **qualification infrastructure is not Phase 3** | **no acquisition has succeeded**, **no backtest has begun**, **Phase 3 is NOT COMPLETE**, **CONTROL stays DEFERRED** and **live trading stays HARD-DISABLED** |

#### Verified status

> **HISTORICAL — the state as of that apply, superseded by *The qualified operator
> access*.** The operator-group, profile and membership-gate lines below record the day of
> the apply and **no longer govern**. Its forward authorization boundaries are unchanged.

```text
PR #60:                                           MERGED
qualification-principal Terraform declarations:   MERGED / APPLIED
controlled saved-plan apply:                      COMPLETED
independent post-apply verification:              PASSED
live customer-managed IAM policies:               2 VERIFIED
live Identity Center permission sets:             2 VERIFIED
live customer-managed-policy references:          2 VERIFIED
live account assignments:                         2 VERIFIED
generated Identity Center runtime roles:          2 VERIFIED
operator group:                                   EMPTY / ASSIGNED / NO HUMAN MEMBERS
human qualification access:                       NONE
governed profiles:                                UNMATERIALIZED
governed SSO login:                               NOT PERFORMED / NOT PROVEN
membership/profile gate:                          ELIGIBLE / NOT EXECUTED
further infrastructure mutation:                  NOT AUTHORIZED
qualification and binding-preflight execution:    NOT AUTHORIZED / NOT RUN
third ADR-0017 acquisition:                       NOT AUTHORIZED / NOT RUN
Run A / Run B / combined assessment:              NOT AUTHORIZED / NOT RUN
provider acquisition:                             NOT AUTHORIZED / NOT RUN
backtesting:                                      NOT STARTED
G1 / G2:                                          OPEN / OPEN
provider selected:                                NONE
Phase 3:                                          NOT COMPLETE
CONTROL:                                          DEFERRED
live trading:                                     HARD-DISABLED
```

**An applied deployment authorizes no run.** Applying the principals closed the infrastructure gate
and **opened none of the others**: membership, profile materialization, binding preflight,
qualification execution, Run A, Run B and the combined assessment each remain a separate written
authorization, and **acceptance, implementation, deployment and execution stay distinct gates that
are never collapsed into one**.

### The merged offline qualification principals — MERGED, OFFLINE-VALIDATED, and nothing is deployed

**PR #56 is merged.** Merge commit **`eb1f8311f2fb65c385ae4b5e916f1b69cdf9e3b1`**, ordered parents
**`26e6b474b7a610600b362d4bce6f75a0304a8b41`** then
**`6726643bdfa92b2de910ae8f02652e8ec24a8dfa`**, merged **2026-09-02T19:15:46Z**, with a **merge
tree identical to the independently validated pull-request head tree**. **PR #56 was independently
reviewed before its merge**, and **the merge introduced no change of its own** — the
pull-request-head-to-merge diff is empty.

**ADR-0021: ACCEPTED / IN FORCE · ADR-0022: ACCEPTED / IN FORCE.** This merge amends neither, and
**no ADR document is edited by it**.

**Implementation: MERGED / OFFLINE-VALIDATED / DORMANT.** Three words, and **none of them implies
the next**: merged means the declarations and the identity code are on `main`; offline-validated
means an isolated `terraform validate` accepted the configuration in a task-owned external copy;
dormant means **nothing has been planned, applied, deployed or run**. **Satisfying the offline
implementation prerequisite authorizes nothing by itself.**

#### The merge

**While PR #56 was open it was OPEN / UNMERGED / BLOCKED ON ARCHITECTURE, and its correction had
not begun** — historical facts about those days that stay true and are **not** rewritten as though
the corrected implementation had always been there. **PR #56 was not defective for obeying
ADR-0021**: it declared the acquisition permission set under exactly the name ADR-0021 accepted,
the independent review found that name unbuildable by the pinned provider, and ADR-0022 corrected
the architecture before the implementation was corrected against it.

**The order was architecture first, implementation second**, and it is preserved: ADR-0022 merged
as PR #57, its post-merge status merged as PR #58, and only then was PR #56 corrected,
independently reviewed and merged.

#### What merged

**The accepted acquisition permission-set name is `KalpaManiQualificationAcquire`**, exactly **29**
characters. **The assessment permission-set name is `KalpaManiQualificationAssessment`**, exactly
**32** characters, and unchanged. Both satisfy the pinned provider's **1-32** name bound, which the
repository's own guards measure from the values rather than transcribe.

```text
locked provider                                   hashicorp/aws 6.62.0
permission-set declarations                       2
customer-managed-policy attachment declarations   2
account-assignment declarations                   2
principal type                                    GROUP
target type                                       AWS_ACCOUNT
session duration                                  PT1H
acquisition profile                               kalpamani-qualification-acquisition
assessment profile                                kalpamani-qualification-assessment
actor-specific identity verification              MERGED
custom IAM role or trust policy                   NONE
IAM user or access key                            NONE
sts:AssumeRole                                    NONE
provider alias, backend or data source added      NONE
bucket or KMS change                              NONE
literal account, group, instance, ARN, region,
start URL or generated suffix                     NONE
```

**Every environment binding is an input with no default**, so a missing binding is a hard error
before any provider call, and **nothing in the merged configuration reads the live environment**.

**ADR-0017 isolation, ADR-0019 write-only acquisition, ADR-0020 request-scoped payload identity and
assessment digest verification are unchanged**, and so is every operation count and deadline term:

```text
acquisition PutObject: 145 to 147
acquisition HeadObject: 0
acquisition GetObject: 0
two successful runs: 290 to 294
assessment: 195 to 196
whole successful package: 485 to 490
L >= 3 * T_s3 + C
remaining >= T_req + 3 * T_s3 + L
```

#### The isolated validation, and its exact scope

**The configuration is merged and provider-validated, and the validation happened only in isolated
external copies.** That scope is the point, and it is stated exactly rather than rounded off:

```text
Terraform CLI used for the validated review       1.15.8
locked provider selected by the committed lock    hashicorp/aws 6.62.0
terraform init -backend=false                     RUN, IN TASK-OWNED EXTERNAL COPIES ONLY
terraform validate                                RUN, IN TASK-OWNED EXTERNAL COPIES ONLY
corrected configuration                           VALIDATED SUCCESSFULLY
retired 33-character name                         INDEPENDENTLY REFUSED BY THE PROVIDER
repository configuration directory initialized    NO
repository .terraform/                            NOT CREATED OR MODIFIED
backend configured                                NO
Terraform state created or modified               NO
real tfvars read                                  NO
terraform plan                                    NOT RUN / NOT AUTHORIZED
terraform apply                                   NOT RUN / NOT AUTHORIZED
provider calls to AWS                             NONE
AWS resource created, changed, discovered or
proved to exist                                   NONE
live environment validation                       STILL REQUIRES SEPARATE AUTHORIZATION
```

**A negative result is what makes the positive one worth having.** The retired 33-character name
was put through the same provider validator and **refused**, so the guard that admits the accepted
name is refusing something rather than agreeing with itself.

**This reconciles with the PR #52 record rather than contradicting it.** The Terraform lines in
*The offline qualification IAM policy foundation* are claims about **this repository's own
configuration directory and about authorized Terraform runs against it**, and **no Terraform
command has been run against that directory**. The validation recorded here ran **only against
task-owned external copies**, under its own separate authorization, and it **initialized no
repository directory, configured no backend, created no state and reached no AWS account**.

**`terraform validate` is not `terraform plan`, and neither is `terraform apply`.** Validation
checks syntax, schema and provider-side attribute rules with no credentials and no account; it
**does not exercise the input-variable rules**, **establishes no live resource**, and is **not**
evidence that applying this configuration would succeed or that any AWS object exists.

#### Status

> **HISTORICAL — the state as of that merge, superseded by *The applied qualification
> infrastructure*.** The qualification Terraform has since been applied under a separate
> authorization and independently verified, so every existence, occurrence and deployment
> line below records that day and **no longer governs**. Its forward authorization
> boundaries are unchanged.

```text
ADR-0021:                                         ACCEPTED / IN FORCE
ADR-0022:                                         ACCEPTED / IN FORCE
PR #56:                                           MERGED
PR #56 merge commit:                              eb1f8311f2fb65c385ae4b5e916f1b69cdf9e3b1
PR #56 merged at:                                 2026-09-02T19:15:46Z
PR #56 merge tree:                                IDENTICAL TO THE VALIDATED HEAD TREE
implementation:                                   MERGED / OFFLINE-VALIDATED / DORMANT
accepted acquisition permission-set name:         KalpaManiQualificationAcquire
assessment permission-set name:                   KalpaManiQualificationAssessment
identity-gate and actor-specific routing:         MERGED, NEVER EXERCISED AGAINST AWS
Terraform configuration:                          MERGED AND PROVIDER-VALIDATED
Terraform validation:                             ISOLATED EXTERNAL COPIES ONLY
Terraform CLI used for the validated review:      1.15.8
locked provider:                                  hashicorp/aws 6.62.0
Terraform plan:                                   NOT RUN / NOT AUTHORIZED
Terraform apply:                                  NOT RUN / NOT AUTHORIZED
Terraform state:                                  NOT CREATED OR MODIFIED BY THE VALIDATION
repository .terraform/:                           NOT CREATED OR MODIFIED BY THE VALIDATION
permission-set declarations:                      MERGED
account-assignment declarations:                  MERGED
policy-attachment declarations:                   MERGED
live permission sets:                             UNCREATED / EXISTENCE NOT ESTABLISHED
live assignments:                                 UNCREATED / EXISTENCE NOT ESTABLISHED
live policy attachments:                          UNCREATED / EXISTENCE NOT ESTABLISHED
runtime roles:                                    UNCREATED / UNOBSERVED
governed profiles:                                UNMATERIALIZED
Organization-instance existence:                  UNESTABLISHED
binding values:                                   UNKNOWN / UNREAD
authority granted:                                NONE
AWS discovery:                                    NOT AUTHORIZED
infrastructure mutation:                          BLOCKED
deployment:                                       NOT PERFORMED
qualification and binding-preflight execution:    NOT AUTHORIZED
Run A:                                            NOT AUTHORIZED / NOT RUN
Run B:                                            NOT AUTHORIZED / NOT RUN
combined assessment:                              NOT AUTHORIZED / NOT RUN
third ADR-0017 acquisition:                       NOT AUTHORIZED
sixth binding preflight:                          NOT AUTHORIZED
G1 / G2:                                          OPEN / OPEN
provider selected:                                NONE
Phase 3:                                          NOT COMPLETE
CONTROL:                                          DEFERRED
live trading:                                     HARD-DISABLED
```

**A merged declaration is not a live resource.** No permission set, assignment, policy attachment,
generated role or governed profile exists because this repository declares one, **whether any such
object exists in AWS is NOT ESTABLISHED**, and **no principal has been granted any AWS authority**.

**Merging an implementation authorizes no infrastructure, no deployment and no run.** The next
separately authorized gate is **not automatically an AWS apply**: **AWS discovery, environment
binding, Terraform plan, Terraform apply, profile materialization, identity preflight and execution
each remain separate gates**, and every downstream operational boundary stays closed.

### The qualification permission-set name limit, and ADR-0022 — ACCEPTED, and architecture only

[ADR-0022](docs/decisions/ADR-0022-qualification-permission-set-name-limit.md) narrowly corrects
one accepted architecture value. **ADR-0022: ACCEPTED / IN FORCE** — **PR #57 merged**, merge
commit **`b214484b0da6edd6192caa01c0e57a9878afc288`**, merged **2026-09-02T15:39:27Z**, with a
**merge tree identical to the independently validated pull-request head tree**. **ADR-0022's
conditional acceptance event has occurred**, and **PR #57 was independently reviewed before its
merge**.

**While PR #57 was open, ADR-0022 was proposed and carried no authority** — a historical fact
about those days that stays true and is not rewritten. **The merge approved architecture only**,
and **no implementation or operational authority followed from the merge**: it authorized no
Terraform command, no AWS, IAM or Identity Center access, no permission-set, assignment, role,
attachment or profile implementation, no infrastructure discovery, mutation or deployment, no
binding preflight, no qualification execution, no Run A, no Run B, no combined assessment, no
CONTROL publication, no ingestion and no trading authority.

**ADR-0021: ACCEPTED / IN FORCE**, and this correction does not change that. It amends one value
ADR-0021 accepted, and **ADR-0021's own document is not rewritten**.

#### The defect, reproduced

**PR #56 was OPEN / UNMERGED / BLOCKED ON ARCHITECTURE while ADR-0022 was decided, and PR #56
has since MERGED** — the blocked period is historical, and the merged implementation is
recorded in *The merged offline qualification principals* above. **PR #56 correctly implemented
ADR-0021 as written**, declaring the acquisition permission set under exactly the name ADR-0021 accepted —
so **PR #56 is not defective for obeying ADR-0021**.

**The PR #56 review found the 33-character provider incompatibility**, and **the independent
review correctly refused the merge**. The pinned provider is **`hashicorp/aws` v6.62.0**, whose
`aws_ssoadmin_permission_set` `name` attribute is validated by
`validation.StringLenBetween(1, 32)` together with the character grammar `[\w+=,.@-]+`, mirroring
the AWS `CreatePermissionSet` API's documented minimum length of 1 and maximum length of 32.

```text
KalpaManiQualificationAcquisition   33 characters   REFUSED on length
KalpaManiQualificationAssessment    32 characters   accepted
KalpaManiQualificationAcquire       29 characters   accepted
```

All three satisfy the allowed-character grammar; **the old acquisition name fails on length
alone**. **The defect was in the accepted architecture, not in the implementation**, which is why
correcting only PR #56 would have left the implementation contradicting the decision governing
it.

#### The decision

**Accepted acquisition permission-set name: `KalpaManiQualificationAcquire`**, exactly **29
characters**, retiring `KalpaManiQualificationAcquisition`. **The retired 33-character name is
historical and defect context, and never the current or proposed replacement.**

**The acquisition generated-role prefix is now**
`AWSReservedSSO_KalpaManiQualificationAcquire_`, as architecture only and **materialized
nowhere**.

#### What it preserves, unchanged

**The assessment permission-set name is unchanged** — `KalpaManiQualificationAssessment`. **Both
profile names are unchanged** — `kalpamani-qualification-acquisition` and
`kalpamani-qualification-assessment`. **The suffix grammar is unchanged**, and ADR-0022 did not
reopen it: the PR #56 review independently approved it. The acquisition and assessment actor
identities and semantics, one-hour sessions, Identity Center group assignments,
customer-managed-policy references, exact-account verification, STS assumed-role parsing and
role-prefix verification are each unchanged. **Exact-account plus actor-specific permission-set
role-name prefix verification is unchanged**, **the session duration is unchanged**, the suffix
grammar still proves **structure, not provenance**, and **no full generated ARN is pinned**.

**ADR-0017, ADR-0019 and ADR-0020 are unchanged** — **ADR-0017 isolation is unchanged**,
**ADR-0019 write-only acquisition is unchanged**, **ADR-0020 request-scoped payload identity is
unchanged**, and **assessment digest verification is unchanged** — and so is every operation
count and deadline term:

```text
acquisition PutObject: 145 to 147
acquisition HeadObject: 0
acquisition GetObject: 0
two successful runs: 290 to 294
assessment: 195 to 196
whole successful package: 485 to 490
L >= 3 * T_s3 + C
remaining >= T_req + 3 * T_s3 + L
```

#### Status

> **HISTORICAL — the state as of that merge, superseded by *The applied qualification
> infrastructure*.** The qualification Terraform has since been applied under a separate
> authorization and independently verified, so every existence, occurrence and deployment
> line below records that day and **no longer governs**. Its forward authorization
> boundaries are unchanged.

```text
ADR-0021:                                         ACCEPTED / IN FORCE
ADR-0022:                                         ACCEPTED / IN FORCE
ADR-0022 acceptance:                              PR #57 merged, architecture only
PR #56:                                           MERGED
PR #56 correction:                                MERGED
accepted acquisition permission-set name:         KalpaManiQualificationAcquire
retired acquisition permission-set name:          KalpaManiQualificationAcquisition
assessment permission-set name:                   UNCHANGED
acquisition and assessment profiles:              UNCHANGED
suffix grammar:                                   UNCHANGED
PR #56 Terraform declarations:                    MERGED / UNAPPLIED
Terraform:                                        UNAPPLIED
permission-set implementation:                    MERGED / OFFLINE-VALIDATED / DORMANT
Identity Center assignments:                      MERGED / UNCREATED / EXISTENCE NOT ESTABLISHED
runtime roles:                                    UNCREATED / UNOBSERVED
customer-managed-policy attachments:              MERGED / UNCREATED / EXISTENCE NOT ESTABLISHED
governed AWS profiles:                            UNMATERIALIZED
Organization-instance prerequisite:               REQUIRED / LIVE EXISTENCE NOT ESTABLISHED
AWS discovery:                                    NOT AUTHORIZED
AWS account/group/instance binding values:        UNKNOWN / UNREAD
authority granted:                                NONE
infrastructure deployment:                        BLOCKED
infrastructure mutation and deployment:           NOT AUTHORIZED / NOT PERFORMED
Terraform isolated init/validate:                 PERFORMED IN EXTERNAL COPIES ONLY
Terraform plan/apply:                             NOT AUTHORIZED / NOT RUN
qualification and binding-preflight execution:    NOT AUTHORIZED / NOT RUN
Run A / Run B / combined assessment:              NOT AUTHORIZED / NOT RUN
third ADR-0017 acquisition:                       NOT AUTHORIZED
sixth binding preflight:                          NOT AUTHORIZED
G1 / G2:                                          OPEN / OPEN
provider selected:                                NONE
Phase 3:                                          NOT COMPLETE
CONTROL:                                          DEFERRED
live trading:                                     HARD-DISABLED
```

**Accepting a correction implements nothing.** **Implementation, infrastructure mutation and
execution stay three separate gates and are never collapsed into one.** **PR #56 has since been
corrected, independently reviewed and MERGED**, under a later, separate authorization: the
correction replaced the retired acquisition permission-set name consistently and added the
provider 1-32 name-length guard. **The genuine isolated `terraform validate` against the pinned
provider was performed in task-owned external copies before that merge**, and **`terraform plan`
and `terraform apply` remain NOT AUTHORIZED / NOT RUN**. **No permission set, assignment, role,
attachment, profile, binding or authority is established.**

### The qualification runtime principal and trust model — ACCEPTED, and nothing is implemented

**ADR-0021: ACCEPTED / IN FORCE.** **PR #54 merged** — merged **2026-09-02T09:01:29Z**, merge
commit **`c58d6c442c34928ad3c25f07368cf1e3323a6552`**, ordered parents
**`620d402849fb7a51b4a78027b4c24b2ebaae1f23`** then
**`0b8d500699468a10c331219c694a8e2fb4e5adee`**, with a **merge tree identical to the
independently validated pull-request head tree**. **ADR-0021's conditional acceptance event has
occurred**, and **PR #54 was independently reviewed before its merge**.

**While PR #54 was open, ADR-0021 was proposed and carried no authority** — a historical fact
about those days that stays true, and that is **not** rewritten as though the decision had
authority before it was accepted. **ADR-0021's own conditional status line is preserved as
history beside its post-merge note rather than rewritten.**

**The merge approved architecture only**, and **no implementation or operational authority
followed from the merge**. It implemented nothing, created nothing, inspected nothing, bound
nothing, deployed nothing, planned nothing and ran nothing. **Runtime principal/trust
architecture: ACCEPTED ARCHITECTURE ONLY.** **Merging an architecture decision authorizes no
implementation, no infrastructure mutation, no deployment and no execution**, and
**implementation, infrastructure mutation and execution stay three separate gates and are never
collapsed into one.**

#### What the decision chooses

**AWS IAM Identity Center is the human authentication root**, and **no IAM user or long-lived
access key is permitted for qualification**. **A dedicated, governed Identity Center operator
group is the assignment subject**, and **the exact identity-store and group identifier is an
environment-binding value and remains unknown and unread**.

**Two separate permission sets exist logically — `KalpaManiQualificationAcquisition` and
`KalpaManiQualificationAssessment`.** **Each permission set is assigned to the governed operator
group in the single target account that already owns the licensed data plane**, and **the
account id is an environment-binding value and must not appear in the proposal**. **Each
assignment causes IAM Identity Center to create and manage a distinct runtime IAM role in that
account.**

**The acquisition permission set references only the merged acquisition managed-policy
declaration from PR #52**, and **the assessment permission set references only the merged
assessment managed-policy declaration from PR #52**. **No custom `aws_iam_role`, custom role
trust policy, source-profile role chain, application AssumeRole, IAM user, access key, ECS task
role, Lambda execution role, EC2 instance profile, web-identity principal or cross-account
principal is part of this architecture.**

**Application entry points continue to use two exact named profiles —
`kalpamani-qualification-acquisition` and `kalpamani-qualification-assessment`** — and **those
profiles use the SDK's IAM Identity Center credential provider and return short-lived,
refreshable credentials for their corresponding permission-set role**.

**Session duration is bounded to one hour per permission set**, which **covers the 1,800-second
run deadline with operational margin without authorizing an unbounded session**.

#### The trust model, precisely

**The governed Identity Center group assignment is the authorization binding.** **IAM Identity
Center manages the generated role and its service trust, and KalpaMani does not author a custom
trust policy under this decision.** **The two permission sets, account assignments,
customer-managed-policy references, session durations and the profile contract are the later
implementation surface.**

**Removing all assignments may delete and later recreate the generated role with a new suffix**,
so the identity gate uses the stable permission-set role prefix plus strict account binding
rather than a stale full ARN. **No live assignment, permission set, role or policy attachment
exists merely because the decision describes it.**

**Role separation is a process and permission separation, not a claim that two different humans
approve the two stages**, and **one governed operator may be assigned both permission sets but
must invoke each actor under its correct profile**.

#### The identity contract

**The acquisition entry point accepts only the acquisition permission-set role identity, and
assessment accepts only assessment**, and **cross-use fails closed before provider, S3 or
private-evidence activity**.

**The identity gate binds the exact target account plus the exact permission-set role-name
prefix and a validated AWS-generated suffix grammar**, and **it does not pin one full generated
role ARN forever, because the suffix may rotate when assignments are removed and recreated**.
**The profile name is routing input, not proof**, and **`sts:GetCallerIdentity` remains the
runtime proof during a later authorized execution**. **Credentials from default-profile
fallback, environment access keys, shared long-lived credential files, a differently named SSO
role, or any other provider chain are refused.**

The decision carries an **exhaustive identity decision table** over eighteen cases, and an
**evaluated set of rejected alternatives** — long-lived IAM users and access keys, one shared
role or permission set, an SSO source role chained into custom roles, direct custom IAM roles
with hand-written trust policies, ECS, Lambda, EC2 and OIDC service principals, cross-account
execution, pinning the complete generated ARN forever, whole-account trust, profile-name-only
authorization, and environment-variable credential fallback.

#### Carried-forward implementation findings

> **HISTORICAL — the state as of that merge, superseded by *The applied qualification
> infrastructure*.** The qualification Terraform has since been applied under a separate
> authorization and independently verified, so every existence, occurrence and deployment
> line below records that day and **no longer governs**. Its forward authorization
> boundaries are unchanged.

Two findings from the independent review are recorded for the later, separately authorized
implementation gate. **Neither expands the accepted decision**, and **neither is a live fact**:
nothing below was read from AWS, and **no account id, group id, instance identifier, start URL,
region, suffix, ARN or profile content is invented, discovered or recorded here**.

**Organization-instance prerequisite: REQUIRED / LIVE EXISTENCE NOT ESTABLISHED.** **The
eventual Identity Center deployment requires an Organization instance with multi-account
permissions enabled**, because an account instance provides neither permission sets nor account
assignments. **Whether such an instance exists is NOT ESTABLISHED**, and it **must be checked
only in a later authorized environment-discovery and binding gate**.

**`sts:GetCallerIdentity` returns an STS assumed-role ARN of the form
`arn:aws:sts::<account>:assumed-role/AWSReservedSSO_<permission-set-name>_<suffix>/<session-name>`**,
and not the IAM role ARN the generated role carries. **The later identity gate must therefore
parse the caller identity form actually returned at runtime** while enforcing **the exact target
account**, **the exact actor-specific permission-set role-name prefix**, **a strict
AWS-generated suffix grammar**, **no loose substring matching**, **no full generated ARN pinned
permanently**, and **no profile-name-only or account-only proof**. **The suffix grammar proves
structure, not provenance**, and **runtime AWS identity is established by
`sts:GetCallerIdentity` plus the binding contract.**

**AWS account/group/instance binding values: UNKNOWN / UNREAD**, and **identity-gate and
profile-constant corrections stay NOT AUTHORIZED / NOT IMPLEMENTED** until that separate gate is
opened.

#### What it preserves

**The decision changes no application behaviour, no stored data and no arithmetic.** ADR-0019
write-only acquisition, conditional `PutObject` collision behaviour, zero acquisition
`HeadObject`, `GetObject`, `GetObjectAttributes` and listing, ADR-0020 execution, request and
digest scoped payload identity, assessment digest recomputation and key reconstruction,
ADR-0017, the shared store and ingestion behaviour, the durable locator schema, the existing
bucket, SSE-S3 choice, deletion model and KMS boundary, the S3 action and resource matrices in
the two PR #52 policy declarations, and the 1,800-second deadline, request inventory, retries,
socket timeouts, operation accounting and assessment envelope are each **unchanged**.

```text
acquisition PutObject: 145 to 147
acquisition HeadObject: 0
acquisition GetObject: 0
two successful runs: 290 to 294
assessment: 195 to 196
whole successful package: 485 to 490
L >= 3 * T_s3 + C
remaining >= T_req + 3 * T_s3 + L
```

**The identity and trust decision adds no S3 operation and changes no deadline term.**

**The merge of PR #54 approved architecture only.** It authorized no discovery of actual
Identity Center instance, identity store, account, group, assignment, profile or region values,
no Terraform implementation of permission sets or assignments, no policy attachment
implementation, no identity-gate code change, no profile creation, no Terraform init, validate,
plan or apply, no AWS policy, role or assignment creation, and no deployment, binding preflight,
qualification, Run A, Run B or assessment. **The next gate after ADR acceptance is an offline
implementation gate** for permission sets, customer-managed-policy attachments, assignments,
profiles, and any proven identity-gate and profile-contract corrections.

#### Status

> **HISTORICAL — the state as of that merge, superseded by *The applied qualification
> infrastructure*.** The qualification Terraform has since been applied under a separate
> authorization and independently verified, so every existence, occurrence and deployment
> line below records that day and **no longer governs**. Its forward authorization
> boundaries are unchanged.

```text
ADR-0021:                                         ACCEPTED / IN FORCE
ADR-0021 architecture:                            ACCEPTED / IN FORCE
PR #54:                                           MERGED — normal merge, two ordered parents
runtime principal/trust architecture:             ACCEPTED ARCHITECTURE ONLY
permission-set implementation:                    MERGED / OFFLINE-VALIDATED / DORMANT
Identity Center assignments:                      MERGED / UNCREATED / EXISTENCE NOT ESTABLISHED
runtime roles:                                    UNCREATED / UNOBSERVED
runtime trust principals:                         NOT SELECTED IN AWS
customer-managed-policy attachments:              MERGED / UNCREATED / EXISTENCE NOT ESTABLISHED
governed AWS profiles:                            UNMATERIALIZED
identity-gate/profile-constant correction:        MERGED / OFFLINE-VALIDATED / DORMANT
Organization-instance prerequisite:               REQUIRED / LIVE EXISTENCE NOT ESTABLISHED
AWS account/group/instance binding values:        UNKNOWN / UNREAD
authority granted:                                NONE
PR #52 policy declarations:                       MERGED / OFFLINE-REVIEWED / UNAPPLIED / UNATTACHED
PR #53 governance synchronization:                MERGED
corrected qualification application:              MERGED / DORMANT / OFFLINE-CONFORMING
ADR-0019 and ADR-0020:                            ACCEPTED / IN FORCE, UNAMENDED
infrastructure binding/deployment:                BLOCKED
infrastructure mutation and deployment:           NOT AUTHORIZED / NOT PERFORMED
Terraform isolated init/validate:                 PERFORMED IN EXTERNAL COPIES ONLY
Terraform plan/apply:                             NOT AUTHORIZED / NOT RUN
Terraform and AWS/provider/credential access:     NOT AUTHORIZED / NOT RUN
AWS/provider/credential access:                   NOT AUTHORIZED / NOT PERFORMED
qualification and binding-preflight execution:    NOT AUTHORIZED / NOT RUN
Run A / Run B / combined assessment:              NOT AUTHORIZED / NOT RUN
third ADR-0017 acquisition:                       NOT AUTHORIZED
sixth binding preflight:                          NOT AUTHORIZED
G1 / G2:                                          OPEN / OPEN
provider selected:                                NONE
Phase 3:                                          NOT COMPLETE
CONTROL:                                          DEFERRED
live trading:                                     HARD-DISABLED
```

**The chronology through PR #54 is preserved and unrewritten.** ADR-0018's architecture was
accepted and its offline implementation merged dormant; ADR-0019 corrected acquisition collision
handling to write-only publication; ADR-0020 corrected qualification payload identity to
execution-and-request scope; the corrected application implementation merged and remained
dormant and offline-conforming; PR #52 merged only the offline qualification IAM policy
declarations and guards and deliberately chose no runtime trust principal; PR #53 synchronized
that governance status; **ADR-0021 was proposed in PR #54 as the first decision to choose the
execution principal and trust model**, which none of them chose; and **PR #54 was independently
reviewed and normally merged, accepting architecture only**. **No earlier ADR is rewritten as
though ADR-0021 had always existed**, **ADR-0021 amends no earlier ADR document**, and
**ADR-0019 and ADR-0020 remain ACCEPTED / IN FORCE and unamended.**

**One historical process violation is recorded, and it is not this session's.** The ADR-0021
proposal session disclosed accidental `aws --version` and `terraform version` guard-self-test
probes, and the independent review evaluated them as **a real historical process violation with
no artifact or infrastructure effect**. That is a fact about **that** session. **It is not a
claim that no prohibited activity ever occurred**, and it is **not** an event of the
synchronization that recorded this status, which ran no AWS and no Terraform command of any
kind.

### The offline qualification IAM policy foundation — MERGED, and nothing is deployed

**PR #52 is merged.** Merge commit **`beb5afa5087ee7488c54b77d2dfd6f3f94bbc68f`**, approved
implementation head **`ce06a61ec7a701228849580395d24ce49cebf824`**, and **PR #52 was independently
reviewed before its merge**. It added one Terraform file declaring the two accepted qualification
permission sets, two named outputs, an infrastructure README correction, and the guards that hold
them in place.

**The merge put Terraform declarations into source control, and that is the whole of it.** Six
statements are kept apart on purpose, and none of them implies the next:

```text
Terraform declarations merged into source control
    DOES NOT MEAN   Terraform initialized, planned or applied
    DOES NOT MEAN   AWS managed policies created
    DOES NOT MEAN   roles, trust principals or attachments selected or implemented
    DOES NOT MEAN   any principal received authority
    DOES NOT MEAN   qualification infrastructure is deployable or executable
```

#### The history, in order

1. **ADR-0018 architecture was accepted, and its offline implementation merged dormant.**
2. **ADR-0019 corrected acquisition collision handling to write-only publication.**
3. **ADR-0020 corrected qualification payload identity to execution-and-request scope, while
   retaining digest verification.**
4. **The corrected application implementation merged and remained dormant and
   offline-conforming.**
5. **PR #52 independently reviewed and merged only the offline qualification IAM policy
   declarations and guards.**
6. **PR #52 deliberately did not choose a runtime trust principal and created no role or
   attachment.**
7. **No Terraform initialization, plan, apply, AWS mutation, deployment or qualification
   execution followed from that merge.**

**This chronology is not rewritten as though the final design existed from the beginning.**
ADR-0018's original arithmetic stays inside its historical markers, ADR-0019's amendment stays the
governing acquisition arithmetic, and ADR-0020's proposed period stays historical. **This merge
amends no ADR**: ADR-0018, ADR-0019 and ADR-0020 are unchanged by it.

#### What the merge did and did not do

**Source control now contains two reviewed `aws_iam_policy` declarations. No authorized
`terraform apply` created those resources, and no AWS existence check occurred. The repository
declares no role, trust policy or attachment for them. Therefore this merge grants no principal
any AWS authority.**

**The declarations are unattached by design.** That is a statement about this repository, and not
about AWS. **Whether any live AWS policy exists is NOT ESTABLISHED**, because establishing it would
take an AWS call that is not authorized — so **no live AWS policy is described here as unattached**,
which would assert an existence nothing has checked.

**Two standing register lines are narrowed by this merge, and neither is edited.** ADR-0019's and
ADR-0020's own status blocks were written before any qualification Terraform existed, and read that
Terraform and IAM are not implemented. **What holds now is narrower, and is stated here rather than
left to inference**: the two permission-set declarations are merged and offline-reviewed; **no role,
trust principal, attachment, plan, apply, deployment or AWS resource exists or is authorized**; and
**further infrastructure design and mutation stay NOT AUTHORIZED**. An accepted decision's own
status text is not rewritten by a later slice, so **this section governs where the two differ**.

#### Why the foundation stops at declarations

| | |
|---|---|
| **the principal is undetermined** | **accepted authority does not yet determine the runtime trust principal** |
| **the entry points pin a profile** | **the operator entry points pin a governed AWS profile and perform the identity gate** |
| **nothing assumes a role** | **the merged entry points do not call `sts:AssumeRole`** |
| **guessing would exceed authority** | **inventing an ECS, Lambda, EC2, federated or human trust principal would exceed accepted architecture** |
| **the next gate is architectural** | **the next architecture gate must choose the execution principal and trust model before roles or attachments can be designed** |

**The policies-only merge does not satisfy deployment readiness**, and is described nowhere as
doing so.

#### The preserved technical boundary

| | |
|---|---|
| **acquisition declaration** | **write-only for claims, request-scoped payloads, records and locators, with read, list and delete denied** |
| **assessment declaration** | **reads only accepted evidence and report prefixes, never claims, and writes only reports** |
| **the report-prefix read action** | **the report-prefix `s3:GetObject` permission exists because AWS authorizes `HeadObject` through that action** |
| **bucket and encryption** | **the existing licensed bucket and SSE-S3 are referenced, and no bucket or KMS change is made** |
| **untouched** | **ADR-0017, shared ingestion, application source, the entry points and the durable locator schema are unchanged** |
| **inert** | **the declarations are inert until a separately authorized principal, attachment, plan and apply sequence exists** |

#### Status

> **HISTORICAL — the state as of that merge, superseded by *The applied qualification
> infrastructure*.** The qualification Terraform has since been applied under a separate
> authorization and independently verified, so every existence, occurrence and deployment
> line below records that day and **no longer governs**. Its forward authorization
> boundaries are unchanged.

```text
ADR-0019 architecture, unchanged by this merge:   ACCEPTED / IN FORCE
ADR-0020 architecture, unchanged by this merge:   ACCEPTED / IN FORCE
corrected qualification application implementation:   MERGED / DORMANT / OFFLINE-CONFORMING
qualification IAM policy Terraform declarations:  MERGED / IN MAIN / OFFLINE-REVIEWED
Terraform initialization for these declarations:  NOT PERFORMED
Terraform plan for these declarations:            NOT AUTHORIZED / NOT RUN
Terraform apply for these declarations:           NOT AUTHORIZED / NOT RUN
AWS managed-policy resource creation from these declarations:   NOT PERFORMED / NOT ESTABLISHED
runtime roles:                                    NOT IMPLEMENTED
runtime trust principals:                         NOT SELECTED
policy attachments:                               NOT IMPLEMENTED
authority granted to a principal by this foundation:   NONE
qualification infrastructure binding/deployment:  BLOCKED
AWS/provider/credential access:                   NOT AUTHORIZED / NOT PERFORMED
qualification and binding-preflight execution:    NOT AUTHORIZED / NOT RUN
Run A:                                            NOT AUTHORIZED / NOT RUN
Run B:                                            NOT AUTHORIZED / NOT RUN
combined assessment:                              NOT AUTHORIZED / NOT RUN
third ADR-0017 authenticated acquisition:         NOT AUTHORIZED
sixth binding preflight:                          NOT AUTHORIZED
G1:                                               OPEN
G2:                                               OPEN
provider selected:                                NONE
Phase 3:                                          NOT COMPLETE
CONTROL:                                          DEFERRED
live trading:                                     HARD-DISABLED
```

**Merging reviewed infrastructure code is not authorization to plan it, apply it or run anything.**
Terraform initialization, validation, plan, apply and every other Terraform command stay **NOT
AUTHORIZED / NOT RUN** for these declarations; **AWS, provider and credential access stay NOT
AUTHORIZED and NOT PERFORMED**; and **qualification infrastructure binding and deployment stay
BLOCKED** until a separate owner authorization chooses the execution principal and the trust model.

### The legitimate duplicate-payload collision, and ADR-0020 — ACCEPTED, and the merged implementation

[ADR-0020](docs/decisions/ADR-0020-request-scoped-qualification-payload-identity.md) narrowly
amends one identity rule, and it has since merged. **ADR-0020 architecture: ACCEPTED / IN FORCE**,
by merge of **PR #49** — merge commit **`e4d328af53f2663c570f94e6c090c3296db8cb9d`**, approved ADR
head **`d9bbb17b7f174c34223eb4736d763f115daf229f`**. **ADR-0020's conditional effectiveness event
has occurred**, and **PR #49 was independently reviewed before its merge**.

**While PR #49 was open, ADR-0020 was proposed and carried no authority**, and **ADR-0018 as
amended by ADR-0019 governed the qualification payload identity before the PR #49 merge** —
historical facts that stay true and are not rewritten as though the amendment had authority before
its merge.

**The merge approved architecture only**, and authorized no production-code correction, no
Terraform, no IAM, no infrastructure mutation, no deployment and no execution.

**PR #48 is not defective for obeying ADR-0019.** It implemented ADR-0019's fail-closed write-only
collision rule correctly and offline, and that correctness is what made a **pre-existing
incompatibility in the accepted architecture** visible. **Its implementation work exposed the
architectural identity gap**, and the separate correction it required has since been made,
independently reviewed and merged.

**PR #48: merged** — merge commit **`f0b39fccdfb36ea69d08fb4def3979b87814b9ff`**, approved
implementation head **`64dc3388f402ee98cf8940d94b42fa16aa7553e2`**, and **PR #48 correction
against ADR-0020: MERGED**. **The merge is an offline implementation correction and nothing
else**: it deployed no infrastructure, created no IAM role, made no AWS or provider request and
ran nothing. **While PR #48 was open it was not ready for review or merge and its correction had
not begun** — a historical fact about those days that stays true and is not rewritten.

#### The history, in order

1. **ADR-0019 was accepted to eliminate acquisition-side object reads.**
2. **PR #48 implemented that rule offline.**
3. **PR #48's implementation work exposed the legitimate duplicate-payload identity conflict.**
4. **No infrastructure was built and no empirical run occurred.**
5. **PR #48 was deliberately left open and unmerged.**
6. **ADR-0020 was proposed to correct the qualification payload identity without weakening
   ADR-0019.**
7. **PR #49 merged, and ADR-0020's architecture became accepted and in force.**
8. **PR #48 could not be reviewed or merged until it was corrected against ADR-0020**, under a
   separate authorization.
9. **PR #50 synchronized ADR-0020's post-merge architecture status.**
10. **PR #48 was then integrated with current main, corrected against ADR-0020, independently
    reviewed and merged**, under that separate authorization.
11. **No infrastructure was deployed and no qualification run occurred during this sequence.**

#### The conflict, stated exactly

**The legitimate duplicate-payload collision** is a conflict between clauses that were each
accepted separately:

| Accepted clause | |
|---|---|
| a complete acquisition run is **exactly 48 requests** and **exactly 144 Bronze `PutObject`** | ADR-0018, and the assessor's fixed-count admission |
| the qualification payload object is **content-addressed**, keyed by `(provider, dataset, digest)` | ADR-0018, inherited from the general-purpose Bronze namespace |
| an acquisition-side **412 fails closed** with no read, no comparison and no adoption | ADR-0019 |

Two byte-equality cases are legitimate rather than pathological: ADR-0018's **page-two
completeness probe** answers **header-only**, which is byte-identical across subjects in one
dataset; and an **unchanged snapshot re-observed eight days later** repeats bytes Run A already
published. Under the pre-amendment derivation the second such write lands on an occupied name,
ADR-0019 correctly fails it closed, and the run halts — so **the accepted complete-run shape was
unreachable whenever a legitimate duplicate payload occurs**. **This is an identity and
key-contract problem, not a reason to weaken write-only acquisition.**

**The conflict is reproducible offline from committed code with synthetic bytes alone.** No real
payload, provider request, S3 operation or private evidence is needed to prove it, and none was
used.

**The scope is exactly one key class.** The acquisition **claim** and **record** keys already bind
the request-scoped acquisition identity, so two governed observations with identical bytes already
receive different claim and record names. Only the payload key was under-scoped.

#### The authoritative identity

**The qualification payload key binds the execution identity, the request ordinal and the payload
digest**, in the structural shape:

```text
<qualification-payload-prefix>/<execution-identity>/requests/<NN>/sha256/<payload-digest>
```

Reconciled with existing naming conventions, that is
`licensed/bronze/<provider>/<dataset>/qualification/<execution-identity>/requests/<NN>/sha256/<payload-digest>`
— under `bronze/`, so prefix-based deletion already covers it. The execution identity is the
accepted run identity the locator and acquisition record already bind; the ordinal is the
deterministic index into the locked 48-request inventory and **cannot be supplied freely by the
provider**; the digest is taken from the exact stored payload bytes. **No provider subject value
appears in a qualification payload key**, and neither does a ticker, date range, API path,
credential, bucket or account.

**Assessment reconstructs the qualification payload key and compares it exactly**, and
**assessment recomputes SHA-256 over the retrieved payload bytes and refuses on any mismatch**,
before parsing. **The key name alone is never treated as integrity proof.**

#### What ADR-0020 does not change

**ADR-0020 preserves ADR-0019's write-only collision policy unchanged.** **Acquisition remains
conditional `PutObject` only**, with no `HeadObject`, no `GetObject`, no `GetObjectAttributes` and
no listing; **a 412 still establishes neither identical nor different content**; and
**`BRONZE_NAME_OCCUPIED` and `LOCATOR_NAME_OCCUPIED` are unchanged**. **No compare, adopt, resume
or deduplicate behaviour is introduced.**

**ADR-0020 supersedes only the qualification payload-key identity rule.** **ADR-0020 does not
supersede ADR-0017**, and **ADR-0020 changes no shared general-purpose Bronze or
S3ResearchObjectStore contract**. **ADR-0020 introduces no locator field** and **ADR-0020
introduces no additional S3 operation**: **ADR-0020 preserves the 485 to 490 package envelope**,
and **ADR-0020 preserves the deadline arithmetic L >= 3 * T_s3 + C**.

The bounded storage cost is stated rather than absorbed: qualification payloads are no longer
globally deduplicated by digest, so identical bytes may be stored more than once, to a maximum of
**96 qualification payload objects** across both runs. That choice is **not generalized to
ingestion or CONTROL storage**.

#### The implementation gap — closed offline, and stated plainly

> **HISTORICAL — the state as of that merge, superseded by *The applied qualification
> infrastructure*.** The qualification Terraform has since been applied under a separate
> authorization and independently verified, so every existence, occurrence and deployment
> line below records that day and **no longer governs**. Its forward authorization
> boundaries are unchanged.

**The architecture blocker that prevented ADR-0020 from being authoritative is resolved. The
implementation blocker is resolved as well, offline.** These are separate states and they are not
collapsed:

| Layer | Current status |
|---|---|
| Architecture | **ADR-0020 accepted and effective** |
| Existing code | **merged, dormant, offline-conforming** |
| Corrective code | **merged — PR #48** |
| Terraform / IAM | **not authorized, not implemented** |
| Deployment | **not authorized, not performed** |
| Execution | **ZERO** |

**A qualification payload-key builder exists**, and **the production implementation now conforms
to the authoritative identity offline**. The merged implementation no longer derives the
qualification payload name from the shared content-addressed builder: it derives it from the
execution identity, the canonical request ordinal and the payload digest, and **assessment
reconstructs that key and recomputes the digest before parsing**.

**Before PR #48 merged no qualification payload-key builder existed**, the production
implementation did not yet conform to the authoritative identity, and the merged ADR-0018 offline
implementation still derived the qualification payload name from the shared content-addressed
builder — historical facts about those days that stay true and are **not** rewritten as though the
request-scoped identity had always been implemented.

**PR #48 was untouched by the ADR-0020 proposal and by its merge** — not edited, rebased, amended,
reviewed, commented on, retitled, closed or merged by either, and auto-merge was not enabled on it
by either. It was inspected read-only, to confirm the conflict. **It was corrected, independently
reviewed and merged later, under a separate authorization**, and that later work is what closed
the implementation gap.

**The ADR-0020 implementation-correction prerequisite is SATISFIED**, and that is the whole of
what it does. **Satisfying the implementation prerequisite does not itself authorize or begin
infrastructure work**, and **the next possible gate is a separate owner authorization for offline
infrastructure, Terraform and IAM preparation**. **Offline-conforming is not deployed, not active,
not operational, not authorized to run and not empirically validated**: *production
implementation* here means code located in production source, never a deployed or running
service.

#### Status

> **HISTORICAL — the state as of that merge, superseded by *The applied qualification
> infrastructure*.** The qualification Terraform has since been applied under a separate
> authorization and independently verified, so every existence, occurrence and deployment
> line below records that day and **no longer governs**. Its forward authorization
> boundaries are unchanged.

```text
ADR-0020 architecture:                    ACCEPTED / IN FORCE
PR #49:                                   MERGED
PR #49 merge commit:                      e4d328af53f2663c570f94e6c090c3296db8cb9d
approved ADR head:                        d9bbb17b7f174c34223eb4736d763f115daf229f
conditional effectiveness event:          OCCURRED
architecture acceptance:                  COMPLETE
PR #48:                                   merged
PR #48 merge commit:                      f0b39fccdfb36ea69d08fb4def3979b87814b9ff
approved implementation head:             64dc3388f402ee98cf8940d94b42fa16aa7553e2
PR #48 correction against ADR-0020:       MERGED
production implementation:                MERGED / DORMANT / OFFLINE-CONFORMING
ADR-0020 implementation:                  MERGED / DORMANT / OFFLINE-CONFORMING
ADR-0018 merged implementation:           DORMANT / OFFLINE-CONFORMING
implementation-correction prerequisite:   SATISFIED
infrastructure design and mutation:       NOT AUTHORIZED / NOT IMPLEMENTED
Terraform / IAM:                          NOT AUTHORIZED / NOT IMPLEMENTED
deployment:                               NOT PERFORMED
execution:                                ZERO
operational or empirical validation:      NOT PERFORMED
Run A:                                    NOT AUTHORIZED / NOT RUN
Run B:                                    NOT AUTHORIZED / NOT RUN
combined assessment:                      NOT AUTHORIZED / NOT RUN
ADR-0019:                                 ACCEPTED / IN FORCE
third ADR-0017 attempt:                   NOT AUTHORIZED
sixth binding preflight:                  NOT AUTHORIZED
G1:                                       OPEN
G2:                                       OPEN
provider selected:                        NONE
Phase 3:                                  NOT COMPLETE
CONTROL:                                  DEFERRED
live trading:                             HARD-DISABLED
```

**Acceptance of ADR-0020 is not authorization to implement or execute it**, and the
implementation that has since merged came from a **separate, later authorization** that authorized
no deployment and no execution of its own. **Merging an implementation authorizes no infrastructure,
no deployment and no run.**

**Neither ADR-0018 nor ADR-0019 is rewritten as though request-scoped keys had always existed.**
ADR-0018's original arithmetic stays inside its historical markers, ADR-0019's figures stay the
governing ones, and **ADR-0020's own conditional status line is preserved as history beside its
post-merge note rather than rewritten**. **PR #48 is not described as having been correct against
ADR-0020 before ADR-0020 existed**: it obeyed ADR-0019, which is what it was written against.

**G1 OPEN · G2 OPEN**, no provider selected, Phase 3 **NOT COMPLETE**, CONTROL publication
**DEFERRED**, live trading **HARD-DISABLED**.

### Non-blocking follow-ups carried forward

Neither blocks A1 acceptance, and neither is authorization to begin work:

- `TradeRecord.orders` deep immutability is a separately governed **Phase-2 hardening** matter,
  outside the A1 data-kernel scope.
- Future provider qualification may expose additional contract requirements. Such a requirement
  creates a **new reviewed version** — it does not rewrite A1's evidence.
