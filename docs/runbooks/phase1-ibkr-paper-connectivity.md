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

You do **not** need to launch TWS or IB Gateway yourself: the `quantconnect/lean` engine
image runs IB Gateway inside the container. If a deployment ever proves otherwise, document
the requirement rather than working around it.

---

## 7. Verify the account is PAPER

Three independent confirmations — all three must agree:

1. **Account id prefix.** `DU` / `DF` / `DI` = paper. `U` / `F` / `I` = **live → ABORT.**
2. **LEAN's own derivation.** LEAN sets `ib-trading-mode` from the account id by regex:
   `^df|^du|^di` → `paper`, `^f|^i|^u` → `live`. Confirm the deployment reports
   `trading-mode: paper`.
3. **Reported equity.** The paper account reports a simulated balance (≈ USD 1,000,000).

`kalpamani.broker.account.BrokerAccountMode.classify()` implements the same rule and
returns `UNKNOWN` for anything unrecognised, so ambiguity fails closed.

> **If there is any doubt whatsoever about paper vs live: abort immediately.**

---

## 8. What success looks like

Look for these log lines:

```
KalpaMani Phase 1 -- IBKR PAPER CONNECTIVITY SMOKE TEST
MODE: READ-ONLY. This algorithm submits NO orders and creates NO positions.
Subscribed symbol: SPY (resolution=Minute)
KalpaMani allocated strategy capital: USD 80,000

[BROKER-STATE:initialize] equity_usd=... cash_usd=... holdings=0 open_orders=0

[MARKET-DATA] FIRST EVENT RECEIVED -- data pipeline is live.
[MARKET-DATA]   symbol      : SPY
[MARKET-DATA]   bar time    : ...
[MARKET-DATA]   close       : ...

[CAPITAL-SEPARATION] Broker equity is NOT KalpaMani strategy capital.
[CAPITAL-SEPARATION]   broker reported equity : USD 1000000
[CAPITAL-SEPARATION]   KalpaMani allocation   : USD 80000
[CAPITAL-SEPARATION]   CONFIRMED DISTINCT: broker equity is 12.50x the KalpaMani allocation.
```

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
| Hangs waiting to connect | 2FA not approved | Approve the IB Key push on IBKR Mobile |
| `Interactive Brokers Lite accounts do not support API trading` | Account is IBKR Lite | Upgrade to IBKR Pro |
| Connection drops every Sunday ~21:00 UTC | Mandatory IBKR weekly restart | Expected — approve 2FA (§9) |
| Existing positions reported | Pre-existing paper positions | **Not KalpaMani's.** Investigate before proceeding; do not liquidate blindly |
| `docker: daemon not running` | Docker Desktop stopped | Start Docker Desktop |
| Preflight fails on git-ignore | `.gitignore` regression | **Stop.** Fix before entering any credential |
| Edits to the algorithm have no effect | Edited the `.runtime/` copy | Edit `lean/projects/...` and re-run preflight |

---

## 12. Phase boundary

Phase 1 ends at a proven read-only connection. Not authorized here: any order (including a
1-share test), any position, IBKR live, strategy logic, borrow logic, options, the risk
engine, or the second IBKR automation username.

Phase 2 — a single tiny **paper** order, fill handling, immediate protection,
reconciliation and clean exit — requires separate explicit authorization.
