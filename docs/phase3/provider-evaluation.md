# Phase 3 — Data Provider Evaluation

**Status: PLANNING. NOTHING HAS BEEN PURCHASED, TRIALLED OR CREDENTIALED.**
**No vendor account exists. No API key has been requested, entered or stored.**

Research performed 2026-08-26. Prices and terms change; every figure below carries the date
it was retrieved and must be re-verified before any purchase authorization (Blueprint
Appendix: *"Re-verify official documentation immediately before implementation"*).

---

## 1. How to read this document

Per the Phase-3 task requirement that current information be **verified rather than
recalled**, every factual claim carries an evidence grade:

| Grade | Meaning |
|---|---|
| **[V]** | **Verified** — the vendor own page was retrieved on 2026-08-26 and states this. |
| **[V2]** | **Verified, secondary** — retrieved from a search index summarising the vendor page or a reseller, not the primary page itself. Weaker; re-verify before relying on it. |
| **[U]** | **Unverified** — could not be retrieved in this session. Stated as a claim to be checked, never as fact. |
| **[Q]** | **SALES QUOTE REQUIRED** — no public price exists. |

And a separate axis, because they are different questions:

| | |
|---|---|
| **proposed** | an architecture or selection this plan recommends |
| **inference** | a conclusion drawn from verified facts, labelled as such |
| **unresolved** | an open question with no answer yet |

**A vendor is never marked point-in-time merely because it offers historical data.** That
distinction is the substance of this evaluation and is applied strictly below.

### Retrieval failures in this session, stated honestly

Several primary sources returned HTTP 403 or gated content to the tooling used:

| Source | Result | Consequence |
|---|---|---|
| `data.sec.gov` (EDGAR APIs) | 403 | EDGAR field-level claims are **[U]** and must be verified in Phase 3A before the design depends on them |
| `www.sec.gov` document pages | 403 | same |
| Nasdaq Data Link product pages | rendered empty | Sharadar professional pricing is **[Q]** |
| `norgatedata.com` prices | interactive calculator only | Norgate prices are **[U]** |
| Financial Modeling Prep pricing | 403 | FMP pricing is **[U]** |
| QuantRocket Sharadar pricing | login-gated | not used |

This is recorded rather than papered over. A plan that cited numbers it could not retrieve
would be exactly the kind of unverified claim §16 of the task forbids.

---

## 2. Provider matrix by domain

Evaluated **per domain**, deliberately, because no single vendor is strong across all of
them — and assuming otherwise is how a data stack ends up with one excellent price feed and
a fabricated estimates history.

### 2.1 Security master · ticker history · delistings (domain A)

| Provider | Depth | PIT capability | Delisted coverage | Access | Cost | Confidence |
|---|---|---|---|---|---|---|
| **Sharadar** (`TICKERS`, `ACTIONS`) | active + delisted "back to the 90s" **[V]** | ticker/table structure is time-indexed; **PIT semantics to be validated in 3A** | >5,000 active + >9,000 delisted companies **[V]** | REST API / bulk | in Bundle, **$29/mo** **[V]** | high |
| **QuantConnect US Equity Security Master** | ~27,500 US equities, from **Jan 1998** **[V2]** | map files + factor files are date-keyed; "free of survivorship bias" **[V2]** | yes — delisted included in universe selection **[V2]** | LEAN CLI download | bundled with LEAN/QC | medium |
| **Norgate** (Platinum+) | to 1990 (Platinum) / 1950 (Diamond) **[V]** | "delisted securities", "historical index constituents", "suitable for backtesting" **[V]** | yes, Platinum and above **[V]** | desktop/Python | price not published **[U]** | medium |
| **Massive** (ex-Polygon.io) | 20+ yrs on Advanced **[V]** | reference/ticker data and ticker events included on all tiers **[V]** | ticker events available; delisting completeness unverified **[U]** | REST | $29–$199/mo **[V]** | medium |
| **EODHD** | 30+ yrs EOD **[V]** | splits/dividends included **[V]**; delisted coverage not stated on pricing page **[U]** | unverified | REST | $19.99–$99.99/mo **[V]** | low-medium |

**Proposed:** Sharadar as primary, **cross-validated against the QuantConnect security
master**, which is already present in the LEAN toolchain and costs nothing extra. Two
independent security masters that agree is a materially stronger claim than one that is
merely asserted, and the disagreement report is itself a data-quality signal
([data-quality-plan.md](data-quality-plan.md)).

### 2.2 Historical universe membership (domain B)

No vendor sells KalpaMani universe. **Membership is constructed** from A + D + F using the
Blueprint §4 rule and stored per session.

| Input | Source | Note |
|---|---|---|
| listed set per date | security master (A) | |
| price | unadjusted daily close (D) | |
| market cap | PIT shares outstanding × price (F) | the field most often wrong |
| ADDV | rolling window of (D) | window ends at or before `as_of` |
| history length | first session in (D) | |

**Proposed:** build it, version it, store it. `universe_definition_version` is part of every
research manifest. **Inference:** this is the highest-leverage anti-survivorship control in
the whole plan, because it is the one place current data would be easiest to reach for.

### 2.3 Market calendar (domain C)

| Provider | Notes | Cost | Confidence |
|---|---|---|---|
| **LEAN `market-hours-database`** | already in the repo toolchain; drives the Phase-2 trading window; ADR-0004 §14 already relies on `SecurityExchangeHours.get_next_market_close` for early closes | free | high |
| `exchange_calendars` (open source) | independent second opinion for cross-validation | free | medium |
| vendor calendars | bundled with most feeds | — | — |

**Proposed:** LEAN as authoritative (it is already what execution obeys — divergence between
research and execution calendars would be its own defect), with `exchange_calendars` as an
independent cross-check.

### 2.4 OHLCV (domain D)

| Provider | History | Unadjusted available | Adjusted-as-of | Cost | Confidence |
|---|---|---|---|---|---|
| **Sharadar `SEP`** | 1998– **[V]** | yes, dividend/split-adjusted and unadjusted columns — **verify in 3A** **[U]** | to be validated | in Bundle **$29/mo** **[V]** | medium-high |
| **QuantConnect / LEAN bundled US equity** | via factor files; used by the backtest engine itself | LEAN stores raw + factor files | native to LEAN | bundled | high |
| **Massive** (ex-Polygon) | 2 yr free / 5 / 10 / 20+ yr by tier **[V]** | yes | adjustment via API params | $0–$199/mo **[V]** | medium |
| **EODHD** | 30+ yrs **[V]** | splits/dividends + adjusted **[V]** | to be validated | $19.99+/mo **[V]** | medium |
| **Databento** | usage-priced $/GB; Standard includes 1 yr L1, more pay-as-you-go **[V]** | tick/L1 native | n/a | usage-based **[V]**, US-equity specifics **[Q]** | medium |
| **Norgate** | 1990 / 1950 by tier **[V]** | yes | yes | **[U]** | medium |

**Proposed:** Sharadar `SEP` as the research source of truth, **cross-validated against the
LEAN bundle**. Databento is over-specified for a 2–30 day horizon and is not recommended for
V1; it is the right answer only if intraday execution research is later authorized.

**Constraint restated:** ADR-0002 §13 and Blueprint §26 forbid broker data as the sole basis
for ranking or backtests. IBKR data is never written into the research store.

### 2.5 Corporate actions (domain E)

| Provider | Announcement vs effective timing | Cost | Confidence |
|---|---|---|---|
| **Sharadar `ACTIONS`** | actions table exists **[V]**; whether an *announcement* timestamp distinct from ex/effective date is carried is **unresolved — validate in 3A** | in Bundle **[V]** | medium |
| **QuantConnect security master** | splits, dividends, delistings, ticker changes **[V2]**; LEAN factor files are effective-date keyed, announcement timing not modelled **[U]** | bundled | medium |
| **Massive** | corporate actions + ticker events on all tiers **[V]** | $29+/mo **[V]** | medium |
| **EODHD** | splits and dividends on all plans **[V]** | $19.99+/mo **[V]** | medium |

**Unresolved, and material:** whether *any* low-cost provider carries a reliable
**announcement timestamp** distinct from the ex-date. If none does, the
[contract](pit-data-contract.md) §6 lag applies (announcement date + 1 session) and the
limitation is recorded. This is a genuine open question, not a formality — defect class 4
depends on it.

### 2.6 Fundamentals (domain F)

| Provider | PIT capability | Restatements | History | Cost | Confidence |
|---|---|---|---|---|---|
| **Sharadar `SF1`** | *"Point-in-time dimension to data with time-indexing to the filing date or the fiscal/report period"* **[V]** | *"Data including or excluding restatements"* **[V]**; dimensions `ARQ/ARY/ART` = **As Reported**, `MRQ/MRY/MRT` = **Most Recent Reported** **[V2]** | from **1997**, 150 indicators, >14,000 companies **[V]** | **$19/mo** standalone, **$29/mo** Bundle **[V]** | **high** |
| **SEC EDGAR** (XBRL company facts, Financial Statement Data Sets) | filing acceptance datetime is the authoritative availability field | as-filed by construction; restatements are separate filings | 2009– for XBRL | **free** | **[U] — 403 in this session** |
| **Intrinio** | *"as-reported and standardized … 1979 to present … point-in-time history for survivorship-bias-free backtesting"* **[V2]** | as-reported + standardized **[V2]** | 1979– **[V2]** | **[Q]** | medium |
| **EODHD Fundamentals** | no PIT statement on the pricing page **[V]** | unverified | — | $59.99/mo **[V]** | low |
| **FMP** | 30+ yrs claimed **[V2]** | unverified | — | **[U]** | low |

**This is the strongest finding in the evaluation.** Sharadar explicitly separates
as-reported from restated *and* time-indexes to the filing date — which is precisely the
bitemporal structure [pit-data-contract.md](pit-data-contract.md) §3 requires — at $19–$29
per month. The `ARQ` dimension is the research default; `MRQ` is available explicitly and
must never be the default.

**Proposed:** Sharadar `SF1` (`ARQ`) as primary; **SEC EDGAR as a free, independent
cross-check** and as the authority on acceptance timestamps. EDGAR is not a fallback here —
it is the only source that is *definitionally* point-in-time, because a filing acceptance
time is a fact about a government system rather than a vendor claim.

**Caveat, explicit:** every EDGAR field-level claim in this plan is **[U]**. `data.sec.gov`
returned 403 to this session tooling. Phase 3A must verify, against the live API, that
`acceptanceDateTime`, `filingDate`, `reportDate`, `form` and `accessionNumber` exist and mean
what this plan assumes — and must honour SEC fair-access requirements (declared User-Agent,
rate limiting) when it does.

### 2.7 Earnings and guidance events (domain G)

| Provider | Announcement **time** | Confirmed vs estimated dates | Cost | Confidence |
|---|---|---|---|---|
| **SEC EDGAR 8-K** | *filing* acceptance time — exact, but later than the press release | n/a | free | **[U]** |
| **Sharadar `EVENTS`** (SEC Form 8-K events) | 8-K derived; from 1993 **[V]** | n/a | in Bundle **[V]** | medium |
| **Wall Street Horizon** | confirmed + forecasted dates *with expected timing*, before/after market **[V2]**; API or FTP, files every 3h 05:00–23:00 ET **[V2]** | explicit confirmed/unconfirmed status **[V2]** | **[Q]** | medium |
| **Zacks / Intrinio** | EPS + sales surprises, consensus **[V2]** | unverified | **[Q]** | low-medium |
| **EODHD / FMP earnings calendar** | date-level; time classification unverified **[U]** | unverified | $59.99+ / **[U]** | low |

**Inference, stated as such:** an 8-K acceptance time is a *lower bound* on public
availability that is usually *later* than the press release. Using it as availability is
therefore **conservative and safe** — it can delay information but never advance it. That is
exactly the direction the [contract](pit-data-contract.md) §5.6 requires.

**Proposed:** EDGAR 8-K acceptance time, plus the next-session-open lag where no verified
announcement timestamp exists. Wall Street Horizon is the correct upgrade if PEAD proves out
and precision becomes worth paying for — deferred, not dismissed.

### 2.8 Analyst estimates and revisions (domain H) — **THE BLOCKING DOMAIN**

| Provider | Historical revision timing | Access | Cost | Confidence |
|---|---|---|---|---|
| **LSEG I/B/E/S** | **yes** — Detail History is daily analyst-level forecasts, US from **1983**; Summary History is monthly consensus snapshots **[V2]** | typically **WRDS institutional licence**; moved to LSEG Workspace from 2024-01-01 with coverage differences vs pre-2024 WRDS **[V2]** | **[Q]** — institutional | medium |
| **FactSet Estimates** | yes | institutional | **[Q]** | **[U]** |
| **Zacks** (direct, or via Intrinio) | consensus estimates for 5,000+ US/Canada companies **[V2]**; **whether historical snapshots carry revision timestamps is unresolved** | API | **[Q]** | low-medium |
| **Bloomberg PIT offering** | marketed as point-in-time for quants **[V2]** | terminal/enterprise | **[Q]** | low |
| **FMP / EODHD analyst estimates** | current or recent estimates; **no evidence of historical snapshot-through-time** | REST | $ low | **NOT ACCEPTABLE as PIT** |

**The finding.** No credible, individually-priced source of historical analyst revision
timing was identified. The genuine sources are institutional and quoted by sales. Retail-tier
"analyst estimates" endpoints return *current* estimates; a current estimate used as a
historical one is the answer sheet, per
[data-domain-inventory.md](data-domain-inventory.md) §H.

**Consequence for Blueprint §6.** Earnings/revision momentum is weighted ~35–40%. The
sub-components split cleanly:

| Sub-component | PIT-available at this budget? |
|---|---|
| EPS / revenue **surprise vs reported** | **yes** — from as-reported fundamentals + reported actuals |
| post-earnings **price/volume** response | **yes** — from OHLCV + event timing |
| margin acceleration, growth from filings | **yes** — Sharadar `ARQ` / EDGAR |
| guidance change | **partial** — text-derived, needs the AI layer |
| **analyst revision velocity** | **NO** |
| **consensus at announcement / surprise vs consensus** | **NO** |

**Proposed handling — and the reason it is not a redesign.** Build the composite from the
PIT-available sub-components. Mark the revision sub-factor **NOT AVAILABLE**. Record the
limitation in every research manifest that touches the composite, and forbid any performance
claim attributed to revision momentum.

This is deliberately *not* proposed as a change to Blueprint §6 weights. CLAUDE.md §2 is
explicit that a lower authority may not silently redesign the system. If, after Phase 3B, the
gap persists and the weights need to change, **that is a separate ADR** raised at the time,
with the evidence. What this plan does is refuse to fill the gap with a number that would
look like the real thing.

**Unresolved, and worth a quote (A3):** whether Zacks historical estimate data — via Intrinio
or directly — carries genuine snapshot-through-time with revision timestamps. If it does, at
a non-institutional price, it materially changes this section. That is the single most
valuable open question in the plan.

### 2.9 Short / borrow data (domain I) — **THE SECOND BLOCKING DOMAIN**

| Provider | Historical borrow fee / availability | Access | Cost | Confidence |
|---|---|---|---|---|
| **IBKR shortable-stock FTP** | **NO HISTORY.** Current fees/availability only — *"there is no historical data on the FTP"* **[V2]** | FTP | free | medium |
| **IBKR SLB / Client Portal** | shows *historical indicative borrow rates*, CSV download **[V2]**; depth, coverage and per-symbol bulk access **unresolved** | manual / portal | free with account | low-medium |
| **ORTEX** | short interest, **cost to borrow**, utilization, days-to-cover, availability **[V]**; Basic delayed / Advanced real-time **[V]**; **historical depth not stated** **[U]** | REST API + Python SDK; API on Advanced, separate API tiers **[V]** | **$49/mo** Basic, **$149/mo** Advanced (or $468/$1,188 annual) **[V]**; API tiers **[U]** | medium |
| **S&P Global Securities Finance** (ex-IHS Markit) | proprietary global securities-finance database: supply, demand, fee, market share; 3M daily transactions over 14+ years **[V2]** | API, SFTP, Snowflake, Xpressfeed **[V2]** | **[Q]** — institutional | medium |
| **EquiLend DataLend** | aggregated, cleansed securities-finance data across asset classes **[V2]** | enterprise | **[Q]** | low-medium |
| **FIS Astec Analytics** | named alongside the above as a global borrow-fee source **[V2]** | enterprise | **[Q]** | low |

**The finding, and it is decisive.** The free source KalpaMani already has a relationship with
— IBKR — publishes **current** borrow data and does not archive it. Everything with real
history is either institutional (**[Q]**) or of unverified depth (ORTEX).

**Therefore:**

> **Short-side research is not authorized, and short backtests are forbidden, until Phase 3C
> qualifies a real historical borrow source.**

Two paths, and the choice is A4:

1. **Fund it.** ORTEX Advanced at $149/mo is the cheapest candidate *if* its history depth
   and API access prove adequate — an open question, not an endorsement. Institutional
   sources are correct and are priced for institutions.
2. **Defer it.** Run V1 long-only. Record that Blueprint §24 direction (*"Long + short"*)
   remains the locked target and that the short family is **unbuilt for lack of data**, not
   abandoned.

**A third option is explicitly refused:** proceeding with assumed borrow. Blueprint §12
already says historical short backtests must be *"discounted unless borrow cost and
availability are modeled conservatively"*, and there is no conservative model of a value that
was never observed. A short backtest on assumed borrow is not a discounted result; it is a
fictional one, and it is biased in the most dangerous direction — the names with the best
short signals are the ones that were hardest and costliest to borrow.

### 2.10 Classification and benchmarks (domain J)

| Provider | Classification history | Cost | Confidence |
|---|---|---|---|
| **Sharadar `TICKERS`** | sector/industry fields present **[V2]**; whether *changes* are historised is **unresolved — validate in 3A** | in Bundle | medium |
| **SEC SIC codes** | free, from filings; coarse and self-reported; changes visible across filings | free | **[U]** |
| **GICS** (S&P / MSCI) | the industry standard; **licensed** | **[Q]** | — |
| benchmark returns | ETF proxies (SPY, sector SPDRs) from the price feed; index levels are licensed | free via proxies | high |

**Proposed:** vendor taxonomy with history if it exists; ETF proxies for benchmark and
sector-relative returns, which sidesteps index licensing entirely and is adequate for
residual momentum. **Static-only classification is acceptable for paper research and must be
recorded as a limitation** — not silently used.

### 2.11 Research-source metadata (domain K)

Free from EDGAR (filings), vendor-supplied for transcripts. **Phase-deferred**: schema now,
population when the AI layer is authorized. No purchase implied.

---

## 3. Tiering

### Open / free or already owned
`SEC EDGAR` **[U]** · `LEAN market-hours-database` · `QuantConnect US Equity Security Master`
· `exchange_calendars` · IBKR *current* borrow (no history) · ETF benchmark proxies

### Practical individual / low-cost
`Sharadar Direct` **$9–$29/mo** **[V]** · `EODHD` **$19.99–$99.99/mo** **[V]** ·
`Massive` (ex-Polygon) **$29–$199/mo** **[V]** · `ORTEX` **$49–$149/mo** **[V]** ·
`Norgate` **[U]** · `FMP` **[U]**

### Institutional
`LSEG I/B/E/S` · `FactSet Estimates` · `S&P Global Securities Finance` · `EquiLend DataLend`
· `FIS Astec Analytics` · `Wall Street Horizon` · `Bloomberg PIT` — all **[Q]**

### Insufficient for point-in-time research, whatever they cost
Any endpoint returning **current** analyst consensus presented as history · any **current**
borrow snapshot presented as history · broker-supplied market data as a ranking source
(forbidden by ADR-0002 §13) · any dataset whose availability timestamp cannot be established
([contract](pit-data-contract.md) §4 rule 5)

---

## 4. Recommended selection, and what it costs

**Proposed Phase 3A/3B stack:**

| Domain | Primary | Cross-check |
|---|---|---|
| security master, tickers, delistings | Sharadar `TICKERS` | QuantConnect security master |
| corporate actions | Sharadar `ACTIONS` | LEAN factor files |
| calendars | LEAN market-hours-database | `exchange_calendars` |
| daily OHLCV | Sharadar `SEP` | LEAN bundled equity data |
| fundamentals (as-reported) | Sharadar `SF1` dimension `ARQ` | SEC EDGAR XBRL |
| filing availability timestamps | **SEC EDGAR acceptance datetime** | — |
| earnings events | SEC EDGAR 8-K + Sharadar `EVENTS` | — |
| universe membership | **constructed and versioned** | — |
| analyst estimates / revisions | **NONE — gap declared** | — |
| borrow history | **NONE — Phase 3C gate** | — |
| classification | Sharadar sector/industry | SEC SIC |
| benchmarks | ETF proxies | — |

### Cost

| | One-time | Recurring |
|---|---|---|
| Phase 3A + 3B as proposed | **$0** | **$29/mo** (Sharadar Bundle) **[V]** — call it **$29–$60/mo** if a second price source is added for cross-validation |
| Annualised | — | **~$350–$720/yr** |
| Phase 3C, cheapest candidate | $0 | **$149/mo** ORTEX Advanced **[V]**, *contingent on unverified history depth* |
| Phase 3C, correct sources | — | **[Q]** institutional |
| Analyst revisions (A3) | — | **[Q]** institutional |

**Inference:** the long-side point-in-time foundation is affordable — roughly the cost of a
streaming subscription. The two blocking domains are the expensive ones, and they are
expensive because they are genuinely hard, not because vendors are opportunistic. That is
the same conclusion Blueprint §18 reached in advance.

---

## 5. Unresolved licensing issues — read before authorizing A2

**This is the most important section for a system that may one day trade real money.**

**1. Sharadar Direct is a PERSONAL USE licence, and this system may outgrow it.** **[V]**

The terms state: *"You may not use the Services or the Services Data (or any derivation of
the Services Data) for professional, commercial, institutional, or organizational purposes of
any kind."* Redistribution is forbidden outright. Derived works — *"research outputs,
backtest results, models, summary statistics, trade logs"* that cannot reproduce the
underlying data — may be retained, and all copies of the data must be deleted within 30 days
of termination.

Personal backtesting is squarely inside that. **Whether managing one own money with an
automated system counts as "professional" is genuinely ambiguous**, and the terms also
restrict *"finance work in a professional capacity"*.

**Unresolved, and it must be resolved before real money, not after:** KalpaMani is currently
a personal research project, which fits. If it becomes an entity, manages outside money, or
is described commercially, the personal licence does not cover it and the professional route
(Nasdaq Data Link, **[Q]**) is required. This should be settled at the same time the
repository returns to PRIVATE for micro-live (CLAUDE.md §3) — the two decisions belong to the
same moment.

**2. Massive (ex-Polygon.io) individual plans are marked "Individual use only" and
"[Non-pros only]".** **[V]** The same professional-status question applies. Note also that
Polygon.io **rebranded to Massive on 2025-10-30** **[V2]** — the API and keys are unchanged,
but documentation and terms now live under a different name, which matters for any recorded
citation.

**3. Redistribution is forbidden by every low-cost vendor examined.** This is compatible with
KalpaMani, which redistributes nothing — but it means vendor data **must never be committed
to this repository**, and the repository is currently **PUBLIC** (CLAUDE.md §3). Vendor
payloads belong under the git-ignored runtime area, for licensing reasons entirely
independent of secrecy. See [implementation-plan.md](implementation-plan.md).

**4. Identifier licensing.** CUSIP and ISIN carry their own licensing regimes. FIGI is
openly licensed. **Proposed:** key on an internal `security_id`, carry FIGI where available,
and treat CUSIP/ISIN as optional and licence-gated — never as the join key.

**5. Databento permits redistribution of most datasets after 24 hours** **[V]** — noted as
unusually permissive, and irrelevant unless intraday research is later authorized.

**6. Exchange market-data entitlements.** Real-time consolidated feeds carry exchange fees
and professional/non-professional status determinations that are separate from any vendor
subscription. V1 research is end-of-day and avoids this entirely. It re-enters at micro-live.

---

## 6. What must be re-verified before any purchase (A2)

1. Every price above, on the vendor own page, on the day of purchase.
2. **Sharadar `SF1` PIT semantics against real data** — that `datekey`/filing-date indexing
   and the `ARQ` dimension behave as the datasheet describes, tested on a company with a
   known restatement.
3. **Whether Sharadar `ACTIONS` carries an announcement timestamp** distinct from ex-date.
4. **Whether Sharadar `TICKERS` historises sector/industry changes.**
5. **SEC EDGAR API field names and fair-access requirements** — unverified in this session.
6. **ORTEX historical depth and API pricing** before any Phase 3C commitment.
7. **The professional/personal licence question** (§5.1), before the system trades real money.
