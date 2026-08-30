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
**PHASE 3A — BOUNDED AUTHENTICATED ACQUISITION QUALIFICATION: IMPLEMENTED — PR #35 MERGED — ATTEMPTED ONCE UNDER SEPARATE AUTHORIZATION AND REFUSED AT THE AWS IDENTITY GATE (`REFUSED_IDENTITY`, EXIT CODE 6). NO PROVIDER REQUEST, NO CREDENTIAL RETRIEVAL, NO PUBLICATION. A SECOND ATTEMPT NOT AUTHORIZED.**
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
| **PHASE 3A — SHARADAR QUALIFICATION RUNTIME CORE** | **IMPLEMENTED / ACCEPTED — PR #17 MERGED — CODE ONLY, NEVER RUN AGAINST SHARADAR OR AWS** |
| **PHASE 3 OVERALL** | **NOT COMPLETE** |
| **Full Stage 3A real-data ingestion** | **NOT AUTHORIZED** |
| **PHASE 3A — A2 / A3 subscription / purchase** | **AUTHORIZED AND PURCHASED (2026-08-28, ADR-0010)** — one month, Full History Bundle, Personal Use, **for qualification only** |
| **Owner-side credential setup · application credential retrieval · provider API access · Services Data ingestion** | Owner-side Sharadar secret creation and identifier configuration **OWNER-CONFIGURED, AND RESOLVED ONCE BY THE ENTRY POINT** on the fifth authorized binding-preflight attempt, which retrieved **one** credential and had it **structurally accepted**. **Additional** application credential retrieval **NOT AUTHORIZED**, provider API access **NOT AUTHORIZED**, Services Data access and ingestion **NOT AUTHORIZED**, a **second** authenticated qualification attempt **NOT AUTHORIZED** — one attempt occurred and refused at the AWS identity gate before reaching any credential; a subscription existing is not permission to use it, a configured secret is not permission to read it again, and a structurally accepted credential is not proof that it authenticates against Sharadar, which stays **UNKNOWN** |
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
| **[ADR-0015](docs/decisions/ADR-0015-implement-the-dormant-sharadar-private-binding-preflight.md) — dormant private-binding preflight** | **ACCEPTED / IN FORCE** — PR #22 merged. One operator entry point exists and is **refused by default**; **binding preflight only**. **Four separately authorized attempts occurred and all four refused, and a fifth separately authorized attempt then COMPLETED** — the four refusing at the identity gate, on a missing local AWS SDK, at the fixed secret-identifier source with **`REFUSED_SECRET_IDENTIFIER`**, and at the identity gate again with **`REFUSED_IDENTITY`** — so **AWS identity-gate activity occurred** and total AWS activity was not zero, while **AWS network requests on the fourth attempt are UNKNOWN** and no **standalone** diagnosis was performed as part of the attempt — though its governed identity gate **invoked its own STS identity operation once**. A **separately authorized post-fourth standalone AWS identity diagnosis has since COMPLETED** with **`REFUSED_SSO_SESSION_MISSING_OR_EXPIRED`** — one process, one `aws sts get-caller-identity` command, exit code **255**, **missing and expired not distinguished**, the governed profile pinned in the child environment and never disclosed, its **own** underlying AWS network-request count **UNKNOWN**, and at that point **SSO-login invocations were ZERO**, **authentication-repair actions were ZERO** and **fifth binding-preflight attempts were ZERO**. A **separately authorized post-diagnosis AWS SSO-login attempt has since COMPLETED** with **`REFUSED_SSO_LOGIN`** — **one** `aws sso login --no-cli-pager` command invocation, **timed out after 420 seconds**, terminated with **no lingering AWS CLI process** and therefore **exit code NOT AVAILABLE / PROCESS TERMINATED ON TIMEOUT**, **browser authorization interactions ZERO**, **device authorizations completed ZERO**, **successful SSO refreshes ZERO**, **identity-confirmation command invocations ZERO**, **fifth binding-preflight attempts ZERO**, its own underlying AWS network-request count **UNKNOWN**, the SSO session **still unrefreshed after it**, the earlier **`REFUSED_SSO_SESSION_MISSING_OR_EXPIRED`** diagnosis **unrevised**, and the likely cause recorded as **suppression of the interactive browser/device-code surface — likely, not proven**. A **corrected second AWS SSO-login attempt has since COMPLETED SUCCESSFULLY** — one `aws sso login --no-cli-pager` command in a new Claude session on a **live console with inherited stdin, stdout and stderr**, **no captured, piped, redirected, buffered or file output**, the **interactive browser/device flow completed**, **exit code `0`**, **no lingering AWS CLI process**, **successful governed SSO refreshes ONE**, a **minimal allowlisted child environment built key-by-key** with **no whole-environment copy** and **no credential-bearing ambient variable copied or inspected**, the governed profile from a **static AST parse of `EXPECTED_PROFILE`** and never disclosed, the **verification URL and one-time device code transient in the live console only**, and its own underlying AWS network-request count **UNKNOWN**. Because that login exited `0`, **exactly one sanitized identity confirmation ran** — `aws sts get-caller-identity --no-cli-pager --output json`, **exit code `0`**, **non-empty `UserId`, `Account` and `Arn` structurally present**, **raw response and private identity values neither displayed nor persisted**, classified **`IDENTITY_CONFIRMED`**, **captured buffers cleared after classification**, its own network-request count **UNKNOWN**, **identity confirmed at the time of that command with no guarantee of current or future session validity**, and **verifying no secret identifier, secret, credential, bucket or provider access**. **The fifth separately authorized attempt then ran exactly once and COMPLETED** — **exit code `0`**, public output exactly `binding preflight completed` and `offline validation completed`, closed outcome **`COMPLETED + VALIDATION_COMPLETED`**, and a last definitively reached stage of **stage 10**: one `preflight_qualification_composition` invocation returning **`VALIDATED_OFFLINE`**. Its conservative counts are identity-gate invocations **ONE, passed**, licensed-bucket resolutions **ONE**, secret-identifier resolutions **ONE**, Secrets Manager client constructions **ONE**, `get_secret_value` invocations **ONE, admitted**, S3 client constructions **ONE**, S3 object operations **ZERO**, provider transport constructions **ONE**, Sharadar/provider requests **ZERO**, offline composition-preflight invocations **ONE**, qualification executions **ZERO**, and underlying AWS network requests **UNKNOWN**. **A credential was definitively retrieved**: one admitted `get_secret_value` returned a `SecretString` the existing credential contract accepted **structurally**, which was passed into the offline composition and **never displayed, logged, persisted, hashed, fingerprinted, measured or summarized** — *usable* meaning structurally acceptable to that contract, with **Sharadar authentication UNKNOWN** because **no provider request occurred**. The fourth attempt still **reached neither licensed-bucket resolution nor the secret-identifier source** and **did not read `KALPAMANI_SHARADAR_SECRET_ID`**; operational secret-identifier configuration is **OWNER-CONFIGURED, AND RESOLVED ONCE BY THE ENTRY POINT** on the fifth attempt, owner setup having occurred **after the third attempt** and **before the fourth**. A **sixth** attempt, **further AWS authentication diagnosis**, **another AWS SSO refresh or login — separately gated**, **additional credential or Secrets Manager access**, **Sharadar/provider access**, **any S3 object operation or publication**, **ingestion, backfill and update** and a **second authenticated qualification attempt stay separately gated and NOT AUTHORIZED** |
| **[ADR-0016](docs/decisions/ADR-0016-correct-private-binding-preflight-failure-boundaries.md) — corrected private-binding failure boundaries** | **ACCEPTED / IN FORCE** — PR #24 merged. Separates **secret-identifier**, **local dependency**, **unclassified** and **credential** refusals. The corrected boundaries were exercised for the first time by the fifth attempt, which passed the identifier stage rather than refusing at it: Secrets Manager client constructions **ONE**, `get_secret_value` invocations **ONE, admitted**, Secrets Manager underlying network requests **UNKNOWN**, real credential retrieval **ONE, structurally accepted**. Operational environment **SYNCHRONIZED AND VERIFIED**, Python dependency lock **ABSENT**, environment **RANGE-CONFORMANT NOT LOCK-CONFORMANT**, further environment resynchronization **SEPARATELY GATED**, a sixth binding-preflight attempt **NOT AUTHORIZED**, additional credential or Secrets Manager access **NOT AUTHORIZED**, a **second** authenticated qualification attempt **NOT AUTHORIZED** — the one attempt that occurred refused at the AWS identity gate, two stages before this boundary, so these corrected refusals were not exercised by it |
| **[ADR-0017](docs/decisions/ADR-0017-bounded-authenticated-sharadar-acquisition-qualification.md) — bounded authenticated acquisition qualification** | **ACCEPTED / IN FORCE** — PR #33 merged. Merge commit **`4fab37cd9468bc48b62a80e49e5a17a203870926`**, approved ADR head **`679863fd7f540f47ae4f47aee8d5e363d72caffd`**. **The merge acceptance condition has occurred**, so ADR-0017 is **no longer PROPOSED** — while its pull request was open it was **not accepted and carried no authority**, which was true then and is not rewritten. **The authenticated acquisition entry point is now IMPLEMENTED, ATTEMPTED ONCE AND REFUSED.** `scripts/sharadar_authenticated_qualification.py` exists, **refuses by default**, and the accepted composition root was **extended, not duplicated**: `QualificationRuntime.execute` now has **exactly ONE production caller**, reached only through that entry point's authorized branch. **Authenticated entry points implemented ONE.** **Implementing it was not permission to use it, and one refused attempt is not permission for a second**: **a second execution of the surface remains separately gated and NOT AUTHORIZED**, and **implementation, execution and empirical qualification remain three distinct gates**. **A separately authorized first execution has since been attempted, in a fresh session, and it REFUSED.** Authenticated qualification attempts **ONE — refused**, entry-point process invocations **ONE**, closed outcome **`REFUSED_IDENTITY`**, exit code **`6`**, last stage definitively reached **stage 5 — the AWS identity gate**, stages 1–4 **PASSED**; AWS identity-gate invocations **ONE, refused**, licensed-bucket resolutions **ZERO**, Terraform command invocations **ZERO**, secret-identifier resolutions **ZERO**, `KALPAMANI_SHARADAR_SECRET_ID` reads **ZERO**, Secrets Manager client constructions **ZERO**, `get_secret_value` invocations **ZERO**, credential retrievals by this attempt **ZERO**, S3 client constructions **ZERO**, provider transport constructions **ZERO**, qualification-runtime executions against real services **ZERO**, application-level provider fetches **ZERO**, Sharadar/provider requests **ZERO**, provider authentication **UNKNOWN**, `PutObject` **ZERO**, conditional `HeadObject` **ZERO**, S3 object-byte reads **ZERO**, S3 qualification operations **ZERO**, CONTROL operations **ZERO**, `.runtime/` writes from this attempt **ZERO**, P1–P9 executions **ZERO**, ingestion and trading operations **ZERO**, and underlying AWS/network interactions **UNKNOWN**; the gate's own STS command invocation is **UNKNOWN** because real pre-STS refusal paths exist, and the **cause of the refusal was not diagnosed and is not inferred**. Cumulative credential retrieval remains **ONE**, from the fifth binding-preflight attempt, and binding-preflight attempts remain **FIVE** — this was **not** a sixth. **A second authenticated attempt, further AWS identity diagnosis and another SSO refresh or login are each NOT AUTHORIZED.** The implemented path preserves **one request = one durable acquisition**, keeps the acquisition runtime's **opaque-payload boundary** with **no parser introduced**, declares **`AcquisitionMode.QUALIFICATION`** with **no fourth mode**, locks **one provider request** with **no pagination** and **no automatic retry** over a **seven-day trailing window**, and publishes byte for byte through the **licensed private Bronze data plane** only as **three durable artifacts** in **exactly three PutObject operations** with **zero-to-three conditional HeadObject metadata checks only after 412**, **zero object-byte reads**, **zero `.runtime/` writes** and **no extra qualification report**, performing **no CONTROL publication**. Full **P1–P9 empirical qualification remains separate and unexecuted**, **no provider is selected**, and **G1 and G2 stay OPEN** |
| **Ingestion runner · ECS task or image · a second authenticated qualification attempt** | **NOT AUTHORIZED** — the first attempt occurred, refused at the AWS identity gate, and authorizes nothing further |
| **CONTROL-classification publication** | **DEFERRED / NOT AUTHORIZED** |
| **Provider purchase — qualification subscription** | **PURCHASED / ACTIVE (2026-08-28, ADR-0010)** |
| **Provider credential state · repository consumption · provider API access · Services Data** | Provider credential state **OWNER API KEY EXISTS / OWNER-ATTESTED / RETRIEVED ONCE BY THE ENTRY POINT AND STRUCTURALLY ACCEPTED / NOT VERIFIED AGAINST SHARADAR**; repository/application credential retrieval **ONE, on the fifth authorized binding-preflight attempt**, consumption **offline composition only**, and **any additional retrieval NOT AUTHORIZED**; provider API access **NOT AUTHORIZED**; Services Data access and ingestion **NOT AUTHORIZED**; a **second** authenticated qualification attempt **NOT AUTHORIZED**, the first having refused at the AWS identity gate and retrieved no credential — an owner-held key is not repository access, a subscription existing is not permission to use it, and a structurally accepted secret is not a credential proven to authenticate against Sharadar, which stays **UNKNOWN** |
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
a second authenticated qualification attempt: NOT AUTHORIZED -- one occurred
    and refused at the AWS identity gate with REFUSED_IDENTITY, exit code 6
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
Sharadar/provider requests: ZERO   ·   credential retrieved: ONE   ·   qualification runs: ZERO
credential status: STRUCTURALLY ACCEPTED   ·   Sharadar authentication: UNKNOWN
AWS credential-provider chain invoked during environment verification: NONE
AWS requests during environment verification: ZERO
binding preflight or composition preflight run during environment verification: NEITHER
composition preflight run: ONCE -- by the fifth binding-preflight attempt, offline
a sixth binding-preflight attempt: NOT AUTHORIZED
further AWS authentication diagnosis: NOT AUTHORIZED
another AWS SSO-login/refresh attempt: SEPARATELY GATED / NOT AUTHORIZED
additional credential or Secrets Manager access: NOT AUTHORIZED
a second authenticated qualification attempt: NOT AUTHORIZED -- one occurred and
    refused at the AWS identity gate   ·   Sharadar/provider access: NOT AUTHORIZED
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
identity-gate invocations on the fourth attempt: ONE -- the gate runs its own STS identity operation
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
credential retrieval: ONE   ·   qualification runs: ZERO
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
a second authenticated qualification attempt: NOT AUTHORIZED -- one occurred
    and refused at the AWS identity gate with REFUSED_IDENTITY, exit code 6
Sharadar/provider access: NOT AUTHORIZED
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
a second authenticated qualification attempt NOT AUTHORIZED.**

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
environment resynchronization, **additional** credential or Secrets Manager access, provider
access, any S3 object operation, and a **second** authenticated Sharadar qualification attempt.
**A first authenticated qualification attempt has since occurred, separately authorized, and it
refused at the AWS identity gate with `REFUSED_IDENTITY` and exit code `6` — it was not a sixth
binding-preflight attempt, it retrieved no credential, it made no provider request, and a second
attempt is NOT AUTHORIZED.**

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

**The first authenticated qualification run remains separately gated, and this slice does not
approach it.** What would still be needed: an authorization, a credential source, a real credential,
a constructed **AWS SDK** client, a resolved licensed bucket, and code that calls something other
than `preflight_qualification_composition`. **The fifth separately authorized binding-preflight
attempt supplied the first five, once and offline** — under its own authorization, in the operator
entry point, not in this module. **The sixth does not exist**: nothing calls anything other than
`preflight_qualification_composition`, so no qualification execution, provider request or S3 object
operation has occurred, and the authenticated run stays a separate, unauthorized decision.

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
constructed only by the dormant composition root (ADR-0014) and its own tests
Sharadar requests sent: ZERO   ·   AWS requests sent: ZERO
```

That claim once ended *"and no composition root exists"*.
[ADR-0014](docs/decisions/ADR-0014-implement-the-dormant-sharadar-qualification-composition-root.md)
built one, so the accurate statement is narrower: a dormant composition root constructs this runtime
from injected values and exposes **offline preflight only**. What still stands between it and a live
run is a separately gated authorization plus the real private bindings — a credential source, a
constructed SDK client, a resolved bucket — and code that calls something other than `preflight`.
**The fifth authorized binding-preflight attempt supplied the first three, once and offline**: a
credential was retrieved and structurally accepted, an S3 client was constructed, and the governed
licensed bucket was resolved. **The fourth does not exist**: nothing calls anything other than
`preflight`, so no qualification execution, provider request or S3 object operation occurred, and
an authenticated qualification run remains a separate, unauthorized decision.

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
                        ATTEMPTED ONCE AND REFUSED. AUTHENTICATED ENTRY POINTS
                        IMPLEMENTED ONE; scripts/sharadar_authenticated_qualification.py
                        REFUSES BY DEFAULT; THE ACCEPTED COMPOSITION ROOT WAS
                        EXTENDED, NOT DUPLICATED, AND
                        QualificationRuntime.execute NOW HAS EXACTLY ONE
                        PRODUCTION CALLER. IMPLEMENTING IT WAS NOT PERMISSION TO
                        USE IT, AND ONE REFUSED ATTEMPT IS NOT PERMISSION FOR A
                        SECOND: A SECOND EXECUTION OF THE SURFACE REMAINS
                        SEPARATELY GATED AND NOT AUTHORIZED, AND IMPLEMENTATION,
                        EXECUTION AND EMPIRICAL QUALIFICATION REMAIN THREE
                        DISTINCT GATES. A SEPARATELY AUTHORIZED FIRST EXECUTION
                        WAS ATTEMPTED IN A FRESH SESSION AND REFUSED --
                        AUTHENTICATED QUALIFICATION ATTEMPTS ONE, REFUSED;
                        ENTRY-POINT PROCESS INVOCATIONS ONE; CLOSED OUTCOME
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
                        SHARADAR/PROVIDER REQUESTS ZERO; PROVIDER
                        AUTHENTICATION UNKNOWN; PUTOBJECT ZERO; CONDITIONAL
                        HEADOBJECT ZERO; S3 OBJECT-BYTE READS ZERO; S3
                        QUALIFICATION OPERATIONS ZERO; CONTROL OPERATIONS ZERO;
                        .runtime/ WRITES FROM THIS ATTEMPT ZERO; P1-P9
                        EXECUTIONS ZERO; INGESTION AND TRADING OPERATIONS ZERO;
                        UNDERLYING AWS/NETWORK INTERACTIONS UNKNOWN; THE GATE'S
                        OWN STS COMMAND INVOCATION UNKNOWN, BECAUSE REAL
                        PRE-STS REFUSAL PATHS EXIST; THE CAUSE OF THE REFUSAL
                        UNDIAGNOSED AND NOT INFERRED -- NOT A MISSING SSO
                        SESSION, NOT AN EXPIRED ONE, NOT A CREDENTIAL DEFECT
                        AND NOT A PROVIDER FAILURE; NO RETRY, DIAGNOSIS, SSO
                        LOGIN OR REPAIR FOLLOWED; THIS WAS NOT A SIXTH
                        BINDING-PREFLIGHT ATTEMPT AND BINDING-PREFLIGHT
                        ATTEMPTS REMAIN FIVE. CUMULATIVE CREDENTIAL
                        RETRIEVALS ONE FROM BINDING ATTEMPT 5. PRESERVES ONE
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
               an ingestion runner · a SECOND authenticated qualification attempt ·
                        CONTROL publication -- one authenticated attempt occurred and
                        refused at the AWS identity gate, and it authorizes no other
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
               a SECOND execution of the bounded authenticated acquisition
                        qualification -- ADR-0017 is ACCEPTED / IN FORCE; one
                        separately authorized first execution has occurred and
                        REFUSED at the AWS identity gate with REFUSED_IDENTITY and
                        exit code 6. Acceptance was not permission to run it, and a
                        refused run is not permission to run it again: the
                        implementation, execution and empirical-qualification gates
                        are never collapsed into one
               further AWS identity diagnosis of that refusal, any authentication or
                        SSO repair, and any retry -- the cause is UNDIAGNOSED and
                        stays UNKNOWN; a refusal is a completed result, not
                        permission to diagnose, repair or try again
               the AWS identity gate, Terraform, secret retrieval, Secrets Manager
                        access, any provider request, any S3 qualification
                        publication and any further authenticated qualification
                        arising from ADR-0017 -- each stays separately gated, both
                        after acceptance and after the one refused attempt
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
               FOURTH-ATTEMPT IDENTITY-GATE INVOCATIONS ONE -- THE GATE RUNS ITS OWN
               STS IDENTITY OPERATION; STANDALONE DIAGNOSTIC COMMANDS ZERO; AWS
               NETWORK REQUESTS UNKNOWN
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
               a second authenticated qualification attempt NOT AUTHORIZED -- one
               occurred and refused at the AWS identity gate with REFUSED_IDENTITY
               and exit code 6, and its cause is UNDIAGNOSED and UNKNOWN
               Sharadar/provider access NOT AUTHORIZED
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

### The bounded authenticated acquisition qualification — ATTEMPTED ONCE, REFUSED AT THE IDENTITY GATE

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
11. **No retry, diagnosis, SSO login, repair or second attempt followed**, and none is authorized.

**The authenticated acquisition entry point is IMPLEMENTED, ATTEMPTED ONCE AND REFUSED.**
`scripts/sharadar_authenticated_qualification.py` exists and **refuses by default**: an ordinary
import performs no lookup, constructs no client, opens no socket and reads no environment variable.
Its CLI is **exactly three arguments**, and every credential, dataset, window, page, retry, bucket,
bulk, ingestion and CONTROL spelling is **refused by name**.

**The accepted composition root was extended, not duplicated.**
`execute_qualification_acquisition` was added to the same module that already builds the client, the
store and the runtime — a second root would have meant widening the single-constructor guard from
one file to two. **`QualificationRuntime.execute` now has exactly ONE production caller**, reachable
only through the entry point's authorized branch.

**Implementing an operator surface was not permission to use it, and one refused attempt is not
permission to make a second.**

```
authenticated entry points implemented      ONE
authenticated qualification attempts        ONE -- REFUSED
entry-point process invocations             ONE
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
provider authentication                     UNKNOWN
PutObject                                   ZERO   ·   conditional HeadObject: ZERO
S3 object-byte reads                        ZERO
S3 object operations for qualification      ZERO
CONTROL operations                          ZERO
.runtime/ writes from this attempt          ZERO
P1-P9 executions                            ZERO
ingestion and trading operations            ZERO
underlying AWS/network interactions         UNKNOWN -- no count is established
STS command invocations by the gate         UNKNOWN -- real pre-STS refusal paths exist
cause of the identity refusal               UNDIAGNOSED -- not inferred, not repaired
credential retrievals, cumulative           ONE -- the fifth binding-preflight attempt's, unchanged
binding-preflight attempts                  FIVE -- unchanged
```

**Implementation, execution and full empirical qualification remain three distinct gates** that are
never collapsed into one. The first two have now been *entered*; **none of the three is closed**. A
**second** execution of the surface is separately gated and **NOT AUTHORIZED**, and so are a further
AWS identity gate invocation, Terraform, secret retrieval, Secrets Manager access, any provider
request and any S3 qualification publication arising from it.

**What the one attempted execution established, and what it did not.** It proves exactly one thing:
that at that moment, in that ordered sequence, **the governed AWS identity gate did not pass**. It
establishes **nothing** about the secret identifier, the stored secret, the credential, Sharadar
authentication, the licensed bucket, dataset accessibility, response content, row count, schema,
subject correspondence, data quality, price-feed provenance, Q7, P1–P9 qualification, provider
selection, ingestion readiness, or G1 and G2. It equally does **not** establish that the credential,
the secret or the configuration is faulty: the refusal is **upstream of all of them**.

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

**Everything the attempt did not reach is unchanged.** No secret identifier was resolved and
`KALPAMANI_SHARADAR_SECRET_ID` was **not read**; no Secrets Manager client was constructed and
`get_secret_value` was **not invoked**; **no credential was retrieved by this attempt** — the
repository's cumulative total stays **ONE**, from binding-preflight attempt 5. No S3 client, no
provider transport, no qualification-runtime execution, **no provider request**, no `PutObject`, no
`HeadObject`, no object-byte read, no CONTROL operation, no `.runtime/` write and no P1–P9
execution. **Provider authentication remains UNKNOWN.**

**This attempt is not a sixth binding-preflight attempt.** Binding-preflight attempts remain
**FIVE**, the fifth of which completed offline validation; that count is untouched by an
authenticated qualification attempt, which is a different surface under a different authorization.

**A second authenticated qualification attempt is NOT AUTHORIZED · further AWS identity diagnosis is
NOT AUTHORIZED · another AWS SSO refresh or login is NOT AUTHORIZED · credential access, Secrets
Manager access, provider access, any S3 publication and full empirical qualification each remain
separately gated and NOT AUTHORIZED.** A refusal is a completed result, not permission to repair and
try again.

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

**Nothing else is resolved by implementing this, or by the one refused attempt.** **No provider is
selected**, **full P1–P9 empirical qualification remains separate and unexecuted**, **G1 OPEN · G2 OPEN
· G3 CLOSED · G4–G7 OPEN**, ADR-0005 **PROPOSED**, INC-0002 **OPEN**, Phase 3 **NOT COMPLETE**,
CONTROL publication **DEFERRED**, live trading **HARD-DISABLED**. Q7 stays
**`PUBLICLY_UNRESOLVED`**.

### Non-blocking follow-ups carried forward

Neither blocks A1 acceptance, and neither is authorization to begin work:

- `TradeRecord.orders` deep immutability is a separately governed **Phase-2 hardening** matter,
  outside the A1 data-kernel scope.
- Future provider qualification may expose additional contract requirements. Such a requirement
  creates a **new reviewed version** — it does not rewrite A1's evidence.
