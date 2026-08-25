# Runbook — Phase 1: IBKR Paper Connectivity

> ## ⚠ PAPER ONLY
> This runbook must **never** be used against the IBKR **live** account. Phase 1 is a
> read-only connectivity proof. Live trading is hard-disabled in code, and there is no
> order-submission path anywhere in this phase. If you cannot positively confirm the
> connected account is a paper account, **abort**.

**Objective**

```
KalpaMani -> LEAN -> IBKR Paper -> account connection -> market data
          -> broker account-state observation -> clean shutdown / reconciliation
```

**Zero orders. Zero positions.**

---

## 1. Prerequisites

| Requirement | Why | Check |
|---|---|---|
| Docker (client **and** server) | LEAN runs in a container; the engine image bundles IB Gateway | `docker version` |
| LEAN CLI | Official QuantConnect deployment tool | `lean --version` |
| QuantConnect account (authenticated) | LEAN CLI needs API access to scaffold and run | `lean whoami` |
| QuantConnect organization tier permitting local live deployment | Local live deployment is a paid capability | see §3 |
| IBKR **Pro** account | IBKR **Lite** does not support API trading | IBKR account settings |
| IBKR **Paper** account id | Paper ids begin `DU`, `DF` or `DI` | IBKR account manager |
| IB Key / IBKR Mobile 2FA enabled | Required by IBKR for API sessions | IBKR → Settings → Secure Login System |

The LEAN CLI is a **development tool**, not a KalpaMani runtime dependency. It is
deliberately absent from `pyproject.toml` and lives in an isolated virtualenv at
`.runtime/tools/leanvenv/`, so the KalpaMani package keeps its zero-dependency guarantee.

```bash
python -m venv .runtime/tools/leanvenv
.runtime/tools/leanvenv/Scripts/python.exe -m pip install lean
```

---

## 2. Secret handling — read before touching credentials

**Never** place a credential in the repository. Specifically, never put an IBKR password,
2FA seed, QuantConnect API token or account id into:

`docs/` · `config/` · `lean/config/` · `lean/projects/` · `src/` · `tests/` · `scripts/`
· `.env.example` · a commit message · a log · an AI chat session

### Where credentials actually live

| Secret | Location | Tracked by git? |
|---|---|---|
| QuantConnect user id + API token | `~/.lean/credentials` (`C:\Users\<you>\.lean\credentials`) | **No** — outside the repository entirely |
| IBKR username / account id / password | LEAN runtime config under `.runtime/lean/` | **No** — `.runtime/` is git-ignored |

Both are outside version control. Their **contents are never read, printed or reported.**

### Prove it before entering anything

```bash
git check-ignore -v .runtime                    # must print a matching rule
git status --porcelain --untracked-files=all    # must NOT list .runtime
python scripts/phase1_preflight.py              # automates both checks
```

If any check fails, **stop**. Do not enter a credential.

### Tracked source vs untracked runtime

LEAN requires the project to sit inside its workspace, and it writes generated state
(`local-id`, logs, config) next to the project. To keep credentials and generated files
out of git while keeping the algorithm reviewable:

```
lean/projects/ibkr_connectivity_smoke/   <- TRACKED source. Edit here.
            |  (scripts/phase1_preflight.py copies)
            v
.runtime/lean/ibkr_connectivity_smoke/   <- UNTRACKED build artifact. Never edit here.
.runtime/lean/lean.json                  <- UNTRACKED LEAN config (holds IB settings)
```

Edits made only in `.runtime/` will be silently overwritten on the next preflight.

---

## 3. QuantConnect authentication

```bash
.runtime/tools/leanvenv/Scripts/lean.exe whoami
```

If it reports *"You are not logged in"*, **you** must authenticate — nobody else may enter
these for you:

```bash
.runtime/tools/leanvenv/Scripts/lean.exe login
```

LEAN prompts for **User id** and **API token**, obtainable from
<https://www.quantconnect.com/account>. They are saved to `~/.lean/credentials`.

Then confirm:

```bash
.runtime/tools/leanvenv/Scripts/lean.exe whoami
```

**Organization tier.** Local live deployment (`lean live deploy`) is a paid QuantConnect
organization capability. If your organization lacks it, Phase 1 stops there — that is a
licensing blocker, and no workaround may be devised.

---

## 4. Initialize the runtime workspace

Once authenticated, scaffold the LEAN workspace **inside the untracked runtime area**:

```bash
cd .runtime/lean
../tools/leanvenv/Scripts/lean.exe init --language python --organization "<your organization name>"
```

This creates `lean.json` and a `data/` directory there (~210 MB of free sample data). Both
are git-ignored. The `--organization` value is recorded as the *working organization* and is
what local live deployment later uses for module licensing — which is why no node prompt
appears at deploy time.

The directory must be empty when `lean init` runs. If a synced project is already present,
move it aside and re-run `scripts/phase1_preflight.py` afterwards to restore it.

---

## 5. Preflight (run before every deployment)

```bash
.venv/Scripts/python.exe scripts/phase1_preflight.py
```

It proves `.runtime/` is invisible to git, syncs the tracked algorithm into the workspace,
statically proves the algorithm contains **no** order-submission API, and prints the launch
checklist. **Exit code must be 0.** If it fails, do not deploy.

---

## 6. Start the connectivity test

```bash
cd .runtime/lean
../../.runtime/tools/leanvenv/Scripts/lean.exe live deploy ibkr_connectivity_smoke
```

Run it **interactively, with no credential flags.** The CLI accepts `--ib-user-name`,
`--ib-account` and `--ib-password`, but passing a password on a command line leaks it into
shell history and the process table. Let the wizard prompt instead.

### Prompts you will answer

| # | Prompt | Answer | Secret? |
|---|---|---|---|
| 1 | *Select a brokerage* | **Interactive Brokers** | no |
| 2 | *Username* | your IBKR username | yes |
| 3 | *Account id* | your IBKR **paper** id — must begin `DU`, `DF` or `DI` | sensitive |
| 4 | *Account password* | your IBKR password — **masked** (`prompt-password`) | yes |
| 5 | *Weekly restart UTC time (hh:mm:ss)* | accept the default `21:00:00` (see §9) | no |
| 6 | *Select a live data feed* | **Interactive Brokers** | no |
| 7 | *Enable delayed market data (true/false)?* | **true** — see below | no |

**No organization or node prompt.** Local deployment reads the working organization from
`.runtime/lean/lean.json`, set by `lean init --organization`. Node selection applies only to
*cloud* live deployment, which we are not using.

**No initial cash or holdings prompt.** The IBKR module declares no `live-cash-balance` or
`live-holdings` option, so LEAN reads cash and positions from the brokerage itself. Nothing
asks you to type a capital figure — and if anything ever does, **do not enter USD 80,000**:
that is KalpaMani's allocation, not a brokerage balance.

**Delayed data must be enabled.** LEAN's own guidance: *"If delayed market data is
disabled, live trading will stop and LEAN will shut down"* when you subscribe to a security
you have no market-data subscription for. Phase 1 proves the pipeline works, not
performance — delayed data is fine for that. **No performance claim may ever rest on
delayed data**, and no new data subscription is purchased in Phase 1.

### 2FA

IBKR sends an **IB Key / IBKR Mobile** push notification. Approve it on your phone. LEAN
waits. This is an operational responsibility of the human operator, never automated and
never delegated to an AI.

You do **not** need to launch TWS or IB Gateway yourself. **Confirmed on the 2026-08-24
deployment:** the `quantconnect/lean` image runs **IBAutomater** which starts **IBGateway
version 1034 (Build 10.39.1f)** inside the container, drives its Swing UI, clicks
*IB API* -> *Paper Trading* -> *Paper Log In*, and reports `Trading mode: paper`. No
operator-launched TWS/IB Gateway process is involved.

---

## 7. Verify the account is PAPER

Three independent confirmations — all three must agree:

1. **Account id prefix.** `DU` / `DF` / `DI` = paper. `U` / `F` / `I` = **live → ABORT.**
2. **LEAN's own derivation.** LEAN sets `ib-trading-mode` from the account id by regex:
   `^df|^du|^di` → `paper`, `^f|^i|^u` → `live`. Confirm the deployment reports
   `trading-mode: paper`.
3. **Reported equity.** The paper account reports a simulated balance (≈ USD 1,000,000).

**Observed confirmation lines** (verified 2026-08-24). Grep the deployment log for:

```
InteractiveBrokersBrokerage.OnIbAutomaterOutputDataReceived(): Click button: [Paper Trading]
InteractiveBrokersBrokerage.OnIbAutomaterOutputDataReceived(): Trading mode: paper
InteractiveBrokersBrokerage.OnIbAutomaterOutputDataReceived(): Click button: [Paper Log In]
```

If `Trading mode:` reads anything other than `paper`, **abort immediately**.

`kalpamani.broker.account.BrokerAccountMode.classify()` implements the same rule and
returns `UNKNOWN` for anything unrecognised, so ambiguity fails closed.

> **If there is any doubt whatsoever about paper vs live: abort immediately.**

---

## 8. What success looks like

**Observed on the validated run (2026-08-24).** Engine log:

```
Trading mode: paper
Window title: [<ACCT> Trader Workstation Configuration (Simulated Trading)]
HandleManagedAccounts(): Account list: <ACCT>
HandleAccountSummary(): Tag: AccountType, Value: INDIVIDUAL
Brokerage.OnAccountChanged(): Account USD Balance: 1000000.00
Connect() finished successfully
Subscribe Processed: SPY (STK SPY USD Smart ARCA) # SubscribedSymbols.Count: 1
ErrorCode: 10167 - Requested market data is not subscribed. Displaying delayed market data.
Event Name "EveryDay: Every 1 min", scheduled to run.
```

Algorithm log:

```
KalpaMani Phase 1 -- IBKR PAPER CONNECTIVITY SMOKE TEST
MODE: READ-ONLY. This algorithm submits NO orders and creates NO positions.
live_mode=True
Subscribed symbol: SPY (resolution=Minute)
KalpaMani allocated strategy capital: USD 80,000
[BROKER-STATE:initialize] NOT READ -- brokerage cash is applied after initialize() returns.
[BROKER-STATE:scheduled-1] equity_usd=1000000.0 cash_usd=1000000.0 holdings=0 open_orders=0
[CAPITAL-SEPARATION] Broker equity is NOT KalpaMani strategy capital.
[CAPITAL-SEPARATION]   broker reported equity : USD 1000000.0
[CAPITAL-SEPARATION]   KalpaMani allocation   : USD 80000
[CAPITAL-SEPARATION]   unallocated difference : USD 920000.0
[CAPITAL-SEPARATION]   CONFIRMED DISTINCT: broker equity is 12.50x the KalpaMani allocation.
[CAPITAL-SEPARATION]   KalpaMani strategy capital remains USD 80,000 and is unaffected by the
                       brokerage balance.
```

The `[CAPITAL-SEPARATION]` block is the point of the whole exercise: the broker reported
USD 1,000,000 and KalpaMani stayed at USD 80,000.

**Market data, confirmed 2026-08-25:**

```
[MARKET-DATA] FIRST EVENT RECEIVED -- data pipeline is live.
[MARKET-DATA]   symbol      : SPY
[MARKET-DATA]   bar time    : 2026-08-25 05:15:00
[MARKET-DATA]   algo utc    : 2026-08-25 09:15:00.000472+00:00
[MARKET-DATA]   close       : 766.38
[MARKET-DATA]   volume      : 360.0
[BROKER-STATE:first-market-data-event] equity_usd=1000000.0 cash_usd=1000000.0 holdings=0 open_orders=0
```

**Timing matters.** That bar arrived at **05:15 ET -- pre-market**, more than four hours
before the regular open, because the subscription sets `extended_market_hours=True`. You do
**not** need to wait for 09:30 ET. Bars flow roughly **04:00-20:00 ET** on a trading day,
and the first one appears within about a minute of connecting.

A run started outside that window connects and observes account state normally but will
never log a bar. That is the market being closed, not a fault -- and the scheduled observer
still proves account state, so such a run is not wasted.

> **Note:** `initialize()` runs *before* LEAN applies brokerage cash
> (`Setup(): Initializing algorithm...` precedes `Setup(): Setting USD cash to ...`).
> Broker equity is therefore observed on a scheduled timer, not at initialize, and not
> only from `on_data` — so account state is provable even when the market is closed.

Success criteria — **all** must hold:

- [ ] LEAN starts
- [ ] IBKR Paper connection succeeds
- [ ] The account is the **paper** account
- [ ] At least one SPY market-data event received
- [ ] Broker account state readable
- [ ] Broker paper equity observed
- [ ] KalpaMani strategy capital remains exactly **USD 80,000**
- [ ] **Zero** orders submitted
- [ ] **Zero** positions created
- [ ] Clean stop

---

## 8.1 IMPORTANT — LEAN disables IBKR's broker-side order guards

Observed on the 2026-08-24 connection. During IB Gateway setup, IBAutomater
**automatically changes safety settings on the brokerage side**:

```
Unselect checkbox: [Read-Only API]
Select checkbox:   [Bypass Order Precautions for API Orders]
Select checkbox:   [Bypass Bond warning for API Orders.]
Select checkbox:   [Bypass price-based volatility risk warning for API Orders.]
Select checkbox:   [Bypass Redirect Order warning for Stock API Orders]
Select checkbox:   [Bypass No Overfill Protection precaution ...]
Set API port textbox value: [4002]
```

**Read this carefully.** Enabling *Read-Only Access* in IBKR account settings does
**not** protect an automated deployment: LEAN unselects the Read-Only API checkbox in
IB Gateway every time it starts, and additionally bypasses IBKR's order-precaution
confirmations. This is required for LEAN to function, and it is not configurable from
the CLI.

**Consequence for KalpaMani:** the broker-side "read-only" safety net **does not exist**
once LEAN is running. The zero-order guarantee in Phase 1 rests **entirely** on our own
code containing no order-submission path — which is why that is enforced statically by
`scripts/phase1_preflight.py` and `tests/unit/test_phase1_broker_safety.py` rather than
trusted to a broker setting or to review.

Do not rely on IBKR Read-Only Access as a control. Treat our static guards as the only
thing standing between the system and an order.

---

## 9. Weekly IB Key reauthentication

IBKR **forces a weekly restart**. LEAN restarts the algorithm every **Sunday at
21:00:00 UTC** (configurable via `ib-weekly-restart-utc-time`), and that restart
**requires fresh 2FA approval** on IBKR Mobile.

This is a standing operational commitment: an unattended deployment will halt until a human
approves the push notification. Blueprint V2.1 §15 treats broker-required
authentication/session maintenance as an operational responsibility of the human operator —
it is **not** trade approval, and it is never automated.

---

## 10. Clean shutdown

Stop the deployment with LEAN's supported mechanism:

```bash
cd .runtime/lean
../../.runtime/tools/leanvenv/Scripts/lean.exe live stop ibkr_connectivity_smoke
```

Or press `Ctrl+C` in an attached (non-`--detach`) session.

**Never use liquidation to stop.** There is nothing to liquidate — the algorithm creates no
positions — and liquidation is not a shutdown mechanism.

### Post-shutdown verification

```bash
docker ps                                        # no lingering LEAN container
git status --porcelain --untracked-files=all     # only intended source/doc/test changes
git check-ignore -v .runtime                     # credentials still untracked
```

Confirm from the shutdown reconciliation block:

```
orders submitted by KalpaMani: 0  (MUST be 0)
holdings at shutdown        : 0  (MUST be 0)
open orders at shutdown     : 0  (MUST be 0)
RESULT: CLEAN. KalpaMani created no orders and no positions.
```

Then confirm independently in the IBKR account manager that the paper account shows no
KalpaMani-created position or open order.

---

## 11. Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| `You are not logged in` | QuantConnect not authenticated | Run `lean login` yourself (§3) |
| Deployment rejected on organization/node | Organization tier lacks local live deployment | Licensing blocker — stop; do not work around it |
| LEAN shuts down shortly after start | Delayed data not enabled and no market-data subscription | Redeploy with delayed data **enabled** |
| `LoginFailed - Login failed. Please check the validity of your login credentials.` | IBKR rejected the credentials | See §11.1 — usually the **paper** password |
| Hangs waiting to connect | 2FA not approved | Approve the IB Key push on IBKR Mobile |
| `Interactive Brokers Lite accounts do not support API trading` | Account is IBKR Lite | Upgrade to IBKR Pro |
| Connection drops every Sunday ~21:00 UTC | Mandatory IBKR weekly restart | Expected — approve 2FA (§9) |
| Existing positions reported | Pre-existing paper positions | **Not KalpaMani's.** Investigate before proceeding; do not liquidate blindly |
| `docker: daemon not running` | Docker Desktop stopped | Start Docker Desktop |
| Preflight fails on git-ignore | `.gitignore` regression | **Stop.** Fix before entering any credential |
| Edits to the algorithm have no effect | Edited the `.runtime/` copy | Edit `lean/projects/...` and re-run preflight |

### 11.1 Diagnosing `LoginFailed`

Observed on the first deployment attempt (2026-08-24). The failure timeline:

```
23:53:10.806  Trading mode: paper            <- paper mode selected correctly
23:53:10.808  Click button: [Paper Log In]
23:53:11.806  Window title: [Authenticating...]
23:53:11.832  IBAutomater error - Code: LoginFailed
```

**Read the gap.** The rejection came **26 milliseconds** after the authenticating window
appeared, and the log contained **zero** references to IB Key, IBKR Mobile or two-factor
authentication. That distinguishes two very different failures:

| Elapsed | Meaning |
|---|---|
| **Milliseconds**, no 2FA lines | IBKR **rejected the credentials outright**. No challenge was ever issued. |
| **Tens of seconds to minutes**, 2FA lines present | A push **was** sent and went unapproved — approve it on IBKR Mobile. |

Causes to check, most likely first:

1. **The paper account has its own separate username and password.** This is the usual
   culprit. IBKR paper credentials are *not* the live account credentials. Reset the paper
   password in IBKR Account Management (*Settings -> Account Settings -> Paper Trading
   Account*) and use that password.
2. **Secure Login System not set to IB Key via IBKR Mobile.** LEAN states this is required:
   *Account Manage Account -> Settings -> User Settings -> Security -> Secure Login System*,
   then select **"IB Key Security via IBKR Mobile"**.
3. **Username typo**, or leading/trailing whitespace pasted into the prompt.
4. **IBKR Lite account.** Lite does not support API trading; IBKR **Pro** is required.
5. **Password expired or contains characters** the automater mishandles — reset it to a
   straightforward alphanumeric password and retry.

#### The exact IBKR dialog tells you which it is

IBAutomater logs the IB Gateway dialog title verbatim. Grep for it:

```
Window title: [Unrecognized Username or Password]
Login failed: Passwords are case sensitive.
```

`Unrecognized Username or Password` is **definitive**: the username or password is wrong.
It rules out 2FA, Secure Login System configuration and account permissions entirely. A
2FA or permissions problem produces a *different* dialog.

#### CRITICAL: re-running does NOT re-prompt for credentials

**`lean live deploy` caches IB settings in `.runtime/lean/lean.json` and silently reuses
them.** It re-prompts for the brokerage and data-feed *selection*, but **not** for the
username, account id, password, delayed-data flag or weekly restart time.

A deployment that failed on bad credentials will therefore **fail again, identically**, no
matter how many times you re-run it. This was observed on 2026-08-24: the second attempt
never prompted for credentials and reproduced the same `LoginFailed` two seconds faster.

Clear the cache before retrying:

```bash
python scripts/clear_ib_credentials.py
```

It refuses to touch a file git does not ignore, removes only `ib-*` keys, and reports what
it removed **by name only** — values are never read or printed. The next deploy will prompt
again.

#### Fixing the credentials

1. **Confirm the paper username.** IBKR Client Portal ->
   *Settings -> Account Settings -> Paper Trading Account*. The paper account has its **own
   username**, usually auto-generated and unrelated to the live username.
2. **Reset the paper password** on that same page. Paper passwords are separate from the
   live password and are a common source of this failure.
3. **Verify in a browser before redeploying.** Log in to the IBKR web portal with the paper
   username and password. If the browser rejects them, the problem is the credentials, not
   LEAN — and you have saved yourself another full container start.
4. **Passwords are case sensitive** (IBKR says so in the dialog). Watch for a stuck caps
   lock, a trailing space from a paste, or characters your password manager transformed.
5. Only if the browser login *succeeds* but LEAN still fails should you look at Secure Login
   System, IBKR Pro vs Lite, or the module version.

---

## 12. Phase boundary

Phase 1 ends at a proven read-only connection. Not authorized here: any order (including a
1-share test), any position, IBKR live, strategy logic, borrow logic, options, the risk
engine, or the second IBKR automation username.

Phase 2 — a single tiny **paper** order, fill handling, immediate protection,
reconciliation and clean exit — requires separate explicit authorization.
