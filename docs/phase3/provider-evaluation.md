# Phase 3 — Data Provider Evaluation

**Status: PLANNING. NOTHING HAS BEEN PURCHASED, TRIALLED OR CREDENTIALED.**
**No vendor account exists. No API key has been requested, entered or stored.**

Research performed **2026-08-26**. Every capability, price, licensing and historical-depth
statement below carries a **claim id** resolving to
[provider-source-register.md](provider-source-register.md), where a reviewer will find the
exact source, the exact wording it supports, and its limitation.

> **Revision 2.** Review of PR #6 found four defects in this document: evidence grades were
> not citations, so nothing could be checked; QuantConnect local data was described as
> "bundled" when it is a paid product; IBKR borrow history was dismissed categorically on
> secondary evidence; and the licensing constraint was noted without a gate. All four are
> corrected. Two conclusions changed materially as a result — §3 and §6.

---

## 1. How to read this document

| Grade | Meaning |
|---|---|
| **`[V]`** | The vendor's own page was retrieved and states it. A reviewer can open the URL. |
| **`[V2]`** | A credible secondary source states it. Weaker; re-verify before relying on it. |
| **`[U]`** | Could not be retrieved, or is stated nowhere. **This is evidence too.** |
| **`[Q]`** | No public price; a sales quote is required. |

And separately: **proposed** (an architecture or selection this plan recommends) ·
**inference** (a conclusion drawn from verified facts, labelled as such) · **unresolved** (an
open question with no answer).

**A vendor is never marked point-in-time merely because it offers historical data.** That
distinction is the substance of this evaluation, and §3 is where it changed a recommendation.

### 1.1 What could not be retrieved

| Source | Result | Consequence |
|---|---|---|
| `sec.gov` and `data.sec.gov` — every path tried | HTTP 403 | **Every EDGAR claim in this plan is `[V2]` at best** (`PSR-SEC-032`…`PSR-SEC-043`). Verifying against the live API is Phase-3A work. |
| QuantConnect Dataset Market listing pages | JavaScript SPA shell | dataset listing prices unobtainable from those pages; the *documentation* pages carry them instead (`PSR-QC-034`, `PSR-QC-035`) |
| QuantConnect organization tier prices | client-side injected | **`[U]`** — the tier that gates CLI access is unpriced in this round (`PSR-QC-035`) |
| Nasdaq Data Link product and publisher pages | rendered empty / gated | professional Sharadar pricing is **`[Q]`** (`PSR-SHD-071`…`PSR-SHD-075`) |
| Norgate `prices.php` | interactive calculator | prices obtained from the package page instead (`PSR-NRG-029`, `PSR-NRG-016`…`PSR-NRG-019`) |
| FactSet Marketplace catalogue | title element only | (`PSR-EST-061`) |
| ORTEX historical depth | **stated on no ORTEX-controlled page** | the decisive question about the leading borrow candidate is **`[U]`** (`PSR-BRW-049`) |

---

## 2. Provider matrix by domain

Evaluated **per domain**, because no vendor is strong across all of them — and assuming
otherwise is how a data stack ends up with one excellent price feed and a fabricated
estimates history.

### 2.1 Security master · ticker history · delistings (domain A)

| Provider | Delisted coverage | Historical ticker mapping | Cost | Claim ids |
|---|---|---|---|---|
| **Sharadar** | active **and** delisted, common stock, Nasdaq/NYSE/NYSEMKT | tickers table is time-structured — **verify in 3A** | in Bundle **$29/mo** | `PSR-SHD-026`, `PSR-SHD-042` |
| **QuantConnect US Equity Security Master** | ~27,500 equities from **Jan 1998**; splits, dividends, mergers, IPO, delistings | map files + factor files | **PAID — $600/yr** (Quant Researcher tier) | `PSR-QC-002`, `PSR-QC-017` |
| **Norgate** (Platinum+) | **"Back to 1990"** (Platinum) / 1950 (Diamond); explicitly *not* claimed complete for the 1950s–60s | **NO — "only the current symbol is provided"** | Platinum **$630/12mo** | `PSR-NRG-022`, `PSR-NRG-005`, `PSR-NRG-012`, `PSR-NRG-018` |
| **Massive** (ex-Polygon) | ticker events + reference data, all history since **2003-09-10** on Starter and above | ticker events | $29–$199/mo | `PSR-MSV-012`, `PSR-MSV-014`, `PSR-MSV-030` |
| **EODHD** | not established on the pricing page | unverified | $19.99+/mo | `PSR-EOD-037` |

**Norgate is disqualified as a security master, and the reason is precise.**
`PSR-NRG-012` records the vendor stating that **only the current symbol is provided** — there
is no historical ticker mapping. A stable `assetid` exists (`PSR-NRG-011`), which solves
identity *within* Norgate, but a research platform that must join to filings, estimates and
events by ticker-at-a-date cannot use it as the master. Norgate remains interesting for
delisted price history, not for identity.

**Proposed:** Sharadar as primary. Cross-validation is a **costed decision**, not a freebie —
see §4.

### 2.2 Historical universe membership (domain B)

No vendor sells KalpaMani's universe. **Membership is constructed** from A + D + F under the
Blueprint §4 rule and stored per session, per definition version, per profile.

Norgate is the one vendor that offers something adjacent — `index_constituent_timeseries()`
answers whether a stock was an index constituent on a given date (`PSR-NRG-028`), while
explicitly *not* selling constituent lists (`PSR-NRG-009`). That is index membership, not our
eligibility rule, so it is a cross-check at best.

**Inference:** this remains the highest-leverage anti-survivorship control in the plan,
because it is the one place current data would be easiest to reach for.

### 2.3 Market calendar (domain C)

| Source | Cost | Note |
|---|---|---|
| **LEAN `market-hours-database`** | free, already present | it is what execution obeys; a research/execution calendar divergence would be its own defect |
| `exchange_calendars` (open source) | free | independent cross-check |

**Proposed:** LEAN authoritative, `exchange_calendars` as the cross-check. This is the one
domain where a free, genuinely independent second opinion exists.

### 2.4 OHLCV (domain D)

| Provider | History | Cost | Claim ids |
|---|---|---|---|
| **Sharadar `SEP`** | 1998– | in Bundle **$29/mo** | `PSR-SHD-042` |
| **QuantConnect / AlgoSeek US Equities, local** | 1998–, survivorship-bias-free, **OTC excluded** | **PAID: Daily/Hour bulk $2,136/yr** + $600/yr updates + mandatory $600/yr security master (Quant Researcher tier) | `PSR-QC-018`, `PSR-QC-020`, `PSR-QC-017` |
| **QuantConnect by-ticker, local** | Daily = **one file per security, full history, 100 QCC = $1** | $1/security one-time + security master | `PSR-QC-022`, `PSR-QC-004` |
| **QuantConnect cloud (free tier)** | minute-to-daily, all Dataset Market asset classes | **free**, cloud only, 200 backtests/day | `PSR-QC-006`, `PSR-QC-007` |
| **Massive** | 2y free / 5y / 10y / 20y+ by tier | $0–$199/mo | `PSR-MSV-009`, `PSR-MSV-030`…`PSR-MSV-032` |
| **EODHD** | 30+ yrs; ~11,000 tickers with 25+ yrs of fundamentals | $19.99–$99.99/mo | `PSR-EOD-037`, `PSR-EOD-027` |
| **Norgate** | 10y / 20y / 1990 / 1950 by tier | $270–$787.50 per 12 months | `PSR-NRG-021`, `PSR-NRG-016`…`PSR-NRG-019` |
| **Databento** | DBEQ.BASIC from **April 2023**; Standard $199/mo gives 1 yr L1, 1 month L2/L3 | $199–$1,750/mo, or ~$0.40/GB | `PSR-DBN-002`, `PSR-DBN-009`, `PSR-DBN-010`, `PSR-DBN-006` |

**Databento is not the right shape for this plan.** Its published plan structure caps deep
history at L0 and gives one year of L1 on the $199 tier (`PSR-DBN-013`), and its US equities
bundles start in 2023 (`PSR-DBN-002`, `PSR-DBN-017`). It is an excellent microstructure
provider and this is a 2–30 day horizon. **Not recommended for V1** — revisit only if intraday
execution research is authorized.

### 2.5 Corporate actions (domain E)

| Provider | Announcement timing distinct from ex-date | Claim ids |
|---|---|---|
| Sharadar `ACTIONS` | **unresolved — validate in 3A** | — |
| QuantConnect security master | splits, dividends, mergers, IPO, delistings; factor files are ex-date keyed | `PSR-QC-002` |
| Norgate | documents split/consolidation/bonus/rights handling and back-adjustment mechanics; **the database is explicitly not static — corrections are applied** | `PSR-NRG-006`, `PSR-NRG-007`, `PSR-NRG-008` |
| Massive | corporate actions + ticker events on all tiers | `PSR-MSV-012` |

**Unresolved, and material:** whether *any* low-cost provider carries a reliable
**announcement timestamp** distinct from the ex-date. If none does, the
[contract §9](pit-data-contract.md) lag applies and `CORPORATE_ACTION_ANNOUNCE_APPROXIMATED`
is declared on every dependent result. Defect class 4 depends on this, so it is provider test
**P3** in [implementation-plan.md](implementation-plan.md) §2.

`PSR-NRG-008` is worth reading even if Norgate is not selected: a vendor stating plainly that
its history is **not static** is exactly the backfill/correction behaviour the profile model
exists to handle.

### 2.6 Fundamentals (domain F) — and a finding that changes the plan

| Provider | Point-in-time claim | Cost | Claim ids |
|---|---|---|---|
| **Sharadar `SF1`** | AR dimensions are *"a point-in-time view with data time-indexed to the date the form 10 regulatory filing was submitted to the SEC"* | **$19/mo** standalone, **$29/mo** Bundle | `PSR-SHD-018`, `PSR-SHD-039`, `PSR-SHD-042` |
| **SEC EDGAR** | `SUB` carries both `filed` and `accepted` (the acceptance date **and time**); four datasets SUB/TAG/NUM/PRE; coverage from 2009-04-15 | **free** | `PSR-SEC-014`, `PSR-SEC-015`, `PSR-SEC-016`, `PSR-SEC-005` — **all `[V2]`** |
| **Intrinio** | as-reported + standardized | Individual **$150/mo**, Startup $333/mo | `PSR-EST-014`, `PSR-EST-016` |
| EODHD Fundamentals | no PIT statement | $59.99/mo | `PSR-EOD-039` |

#### The finding: Sharadar is a two-view model, not a revision chronology

This is the single most consequential correction in revision 2, and it comes from Sharadar's
own documentation rather than from testing:

| Dimension | What the vendor says | Claim id |
|---|---|---|
| **AR** (`ARQ`/`ARY`/`ART`) | *"a point-in-time view … time-indexed to the SEC form 10 filing date, and **excludes restatements**"* | `PSR-SHD-018`, `PSR-SHD-015` |
| **MR** (`MRQ`/`MRY`/`MRT`) | *"include restatements"*, *"time indexed to the financial/report period"*, presenting *"the most recently reported data for that reporting period"* | `PSR-SHD-019` |

Map that onto the revision views in [contract §6](pit-data-contract.md):

| View | Sharadar support |
|---|---|
| `ORIGINAL_FILING_ONLY` | **yes** — `ARQ`, keyed to the filing date. Sound. |
| `LATEST_RESTATED` | **yes** — `MRQ`. Sound, and correctly forbidden in research. |
| **`AS_KNOWN_AT_AS_OF`** | **NO.** |

`AS_KNOWN_AT_AS_OF` needs to know *when* each restatement became public. `AR` excludes
restatements entirely; `MR` includes them but is indexed to the **report period, not the
filing date**, so a restated value carries no timestamp saying when it became knowable. There
is no third dimension. `lastupdated` is documented as *"the last date on which a record was
updated"* — a single scalar per row, consistent with in-place overwriting rather than
versioning (`PSR-SHD-022`).

**Consequences, stated plainly:**

1. **With Sharadar alone, the default revision view is not achievable.** Only
   `ORIGINAL_FILING_ONLY` is soundly available, and every run carries
   `REVISION_CHRONOLOGY_INCOMPLETE`.
2. **`AS_KNOWN_AT_AS_OF` must be built from SEC EDGAR**, where each amended filing has its own
   acceptance timestamp and `SUB.prevrpt` flags a submission later amended (`PSR-SEC-021`).
   That makes EDGAR not a cross-check for this view but **its only source**.
3. Provider test **P6** in [implementation-plan.md](implementation-plan.md) §3 stays blocking —
   the documentation tells us the answer, and the test confirms it against real data rather
   than trusting a doc page, per ADR-0003 §4.

**Proposed:** Sharadar `SF1` (`ARQ`) for as-reported fundamentals; **SEC EDGAR as the
authority on acceptance timestamps and as the only route to `AS_KNOWN_AT_AS_OF`**. EDGAR is
definitionally point-in-time — a filing acceptance time is a fact about a government system,
not a vendor claim.

**Caveat, unchanged:** every EDGAR field claim here is `[V2]`, from mirrors and wrappers, not
from sec.gov. Phase 3A verifies against the live API, honouring the documented 10 requests/sec
limit and User-Agent declaration (`PSR-SEC-008`, `PSR-SEC-009`).

### 2.7 Earnings and guidance events (domain G)

| Source | Announcement **time** | Cost | Claim ids |
|---|---|---|---|
| **SEC EDGAR 8-K** | acceptance date **and time** recorded in the submission header | free | `PSR-SEC-015`, `PSR-SEC-028` |
| Sharadar `EVENTS` | 8-K derived | in Bundle | `PSR-SHD-042` |
| **Wall Street Horizon** | confirmed/forecasted dates with expected timing | **`[Q]`** | see `ERN` section |
| Benzinga earnings API | a `time` field (e.g. `16:00:00`) plus `date_confirmed` | — | `PSR-BRW-001`, `PSR-BRW-002` |

**Relevant and slightly awkward:** SEC C&DI 105.07 addresses a company issuing an earnings
release *after* the market close and furnishing the 8-K later (`PSR-SEC-027`). That confirms
the press release generally **precedes** the filing.

**Inference, stated as such:** using 8-K acceptance time as `public_available_time` is
therefore **conservative and safe** — it can delay information but never advance it, which is
the direction [contract §12.5](pit-data-contract.md) requires. It is not *accurate*; PEAD
event-window precision is degraded and `EARNINGS_TIME_APPROXIMATED` is declared.

### 2.8 Analyst estimates and revisions (domain H) — the first blocking domain

The most valuable open question from revision 1 was whether a non-institutional point-in-time
estimates route exists. **It has been answered, and the answer is no.**

| Provider | True historical snapshots with timing? | Access | Claim ids |
|---|---|---|---|
| **FactSet Estimates Point-in-Time** | **yes** — *"daily consensus data relative to the local midnight for each company"*, global history **from 1999** | **`[Q]`**, sales | `PSR-EST-003`, `PSR-EST-007`, `PSR-EST-056` |
| **LSEG I/B/E/S Broker Estimates** | **yes** — analyst-level estimates with *"announcement dates"*, US **from 1976** | **`[Q]`**, sales | `PSR-EST-022`, `PSR-EST-024`, `PSR-EST-057` |
| **WRDS I/B/E/S** | yes — `ESTDATS` per estimate row | **ACADEMIC / NON-COMMERCIAL ONLY** | `PSR-EST-028`, `PSR-EST-034` |
| **Zacks Data (direct)** | *claims* point-in-time; consensus history from 1979/1982; "Analyst Revisions" feeds; analyst-level detail **buy-side institutional only** | **`[Q]`** | `PSR-EST-037`, `PSR-EST-040`, `PSR-EST-039`, `PSR-EST-038`, `PSR-EST-059` |
| **Intrinio → Zacks EPS Estimates** | **NO** | Enterprise only | `PSR-EST-010`, `PSR-EST-011`, `PSR-EST-017` |

**Three findings that close the question:**

**1. The retail-accessible Zacks route is not point-in-time.** Intrinio's Zacks EPS Estimates
object has exactly one date-typed field, `date`, documented as *"the period end date"*
(`PSR-EST-010`). The only backward-looking values are four fixed lookbacks —
`mean_7_days_ago`, `mean_30_days_ago`, and so on (`PSR-EST-011`). That is a current consensus
with a short rear-view mirror, **not** a queryable history of what consensus stood on an
arbitrary past date. And it requires Enterprise access anyway (`PSR-EST-017`); the published
$150/mo Individual and $333/mo Startup plans exclude analyst estimates entirely
(`PSR-EST-015`).

**2. WRDS is off the table on licence, not on price.** *"The WRDS services are for academic
and non-commercial research purposes only"* (`PSR-EST-034`). Even with access, KalpaMani could
not use it.

**3. Even the gold standard has chronology gaps.** The I/B/E/S vendor documentation states
that where an analyst changed an estimate three or more times in a month, only the two latest
changes were captured, and that error corrections *"may be imprecise"* in timing
(`PSR-EST-048`, `PSR-EST-049`). Worth knowing before treating any
revision series as exact.

**Unresolved, and now the single most valuable remaining question:** whether **Zacks Data
direct** supplies genuine as-of consensus snapshots at a workable frequency, and at what price
(`PSR-EST-068`). Zacks advertises point-in-time (`PSR-EST-037`) but publishes nothing about
snapshot frequency and no price. That is one sales conversation — which is authorization
**A5**, not something this plan performs.

> **A current consensus value with no historical snapshot or revision timing is NOT ACCEPTABLE
> for point-in-time backtesting.** It is not a degraded version of the right data; it is the
> answer sheet.

**Decision** (ADR-0005 §16): build the Blueprint §6 composite from its PIT-available
sub-components, mark the revision sub-factor `ANALYST_REVISIONS_UNAVAILABLE`, attribute no
performance to it, and **propose no change to the Blueprint weights.**

### 2.9 Borrow data (domain I) — the second blocking domain

**Revision 1 said "IBKR does not archive historical borrow data". That claim is withdrawn, and
it was wrong in a way that mattered.** It rested on one secondary source — a forum post saying
the FTP feed carries only current fees (`PSR-IBK-041`, **`[V2]`**) — and generalised *the FTP
feed* to *everything IBKR offers*. IBKR's own documentation describes **four** historical
borrow surfaces, one of them programmatic through the very API this system already connects to.

#### What IBKR actually documents

| Surface | Historical content | Depth | Access | Claim ids |
|---|---|---|---|---|
| **TWS API `reqHistoricalData`, `whatToShow=FEE_RATE`** | OHLC bars where Open = *"Starting Fee Rate"*, High/Low = highest/lowest, Close = *"Last fee rate"*, Volume N/A. *"available in various units of duration up to the present moment"* | **`[U]` — stated nowhere** | **programmatic**, per contract | `PSR-IBK-010`, `PSR-IBK-034`, `PSR-IBK-001`, `PSR-IBK-043` |
| **Client Portal SLB tool** | *"View historical indicative borrow rates and download these rates in a comma-separated values (.csv) file"*; min/max/mean per day | **prior 10 days** | UI + CSV; bulk upload by file | `PSR-IBK-007`, `PSR-IBK-017`, `PSR-IBK-024`, `PSR-IBK-020`, `PSR-IBK-029` |
| **TWS SLB Rates window** | *"charted daily rate history and intraday time & sales of stock loan fees"*; bar graph of the prior 10 days | **prior 10 days** | UI | `PSR-IBK-006`, `PSR-IBK-031` |
| **Securities Lending Dashboard (Orbisa)** | Utilization, Borrower/Lender Depth, Average Duration free; Short Interest Indicator, On-Loan Quantity/Value, Days To Cover premium | **12 months**, premium only | UI, **$12.99** premium | `PSR-IBK-036`, `PSR-IBK-039`, `PSR-IBK-012`, `PSR-IBK-038`, `PSR-IBK-040` |
| Public FTP `shortstock` | symbol, currency, name, identifiers, ISIN, rebate & fee rates, shares available | **`[U]`** whether dated files are retained; `[V2]` says current only | `ftp2.interactivebrokers.com`, user `shortstock`, empty password | `PSR-IBK-027`, `PSR-IBK-028`, `PSR-IBK-046`, `PSR-IBK-041` |

**The `FEE_RATE` finding is the important one**, and revision 1 missed it entirely. It is a
documented historical-data function on the TWS API — the same API LEAN already uses to reach IB
Gateway. If its depth reaches several years, Phase 3C's blocking domain may be substantially
resolved by an interface this system already has, at no vendor cost. If it reaches ten days,
it is worthless for backtesting. **Nothing in IBKR's public documentation says which**
(`PSR-IBK-043`), and this plan will not find out by connecting — that is broker interaction,
and it is authorization **A6**, not planning.

#### Four limitations that survive whatever the depth turns out to be

1. **It is IBKR's book, not the market's.** IBKR describes the SLB system as showing quantity,
   lender count and indicative rates *"based on IBKR client holdings"* (`PSR-IBK-013`). That is
   the correct quantity for *our* execution and an idiosyncratic one for market-wide research —
   which is why `borrow_snapshot.source` is part of the primary key
   ([conceptual-schema.md](conceptual-schema.md) §13).
2. **The live shortable tick is bucketed, not exact** — >2.5 means *"at least 1000 shares
   available"*, >1.5 means available if shares can be located (`PSR-IBK-011`).
3. **The rate is indicative and settles late.** *"Borrow costs tend to fluctuate daily … the
   actual cost can only be determined at the end of the day"* (`PSR-IBK-033`, `PSR-IBK-035`).
4. **No permitted-use statement was found.** No public IBKR page states a licence,
   redistribution restriction or use grant for SLB / shortstock / borrow-rate data
   (`PSR-IBK-044`). Absence of a stated restriction is not a grant.

Every IBKR product page returned HTTP 403 to the fetch tool and was read by plain HTTP client
instead (`PSR-IBK-045`) — recorded because it explains why these are `[V]` rather than `[U]`.

#### The rest of the market

| Provider | Historical depth | Bulk / universe access | Cost | Claim ids |
|---|---|---|---|---|
| **ORTEX** | **`[U]` — stated on no ORTEX page.** `[V2]` sources say **back to 2018** | per-stock endpoints take `from_date`/`to_date`; **every multi-name endpoint is a single-date snapshot** | platform $49/$149; **API sold separately**: Trader $49 (single-stock only), **Quant $149 (bulk endpoints)**, Developer $499 | `PSR-BRW-049`, `PSR-BRW-029`, `PSR-BRW-031`, `PSR-BRW-009`, `PSR-BRW-008`, `PSR-BRW-011`, `PSR-BRW-012` |
| **S3 Partners via AWS Data Exchange** | **since 2015**, *"All historical revisions"*, 70,400+ securities | daily + historical files, CSV | listing says *"available free of charge"*; retail offering via contact | `PSR-BRW-024`, `PSR-BRW-023`, `PSR-BRW-025`, `PSR-BRW-026` |
| **S&P Global Securities Finance** | ~3M daily transactions; program data sourced since 2002 | SQL, Cloud, Snowflake | **`[Q]`** | `PSR-BRW-037`, `PSR-BRW-036` |
| **EquiLend DataLend** | **two years** via API | files, UI, Excel, API | **`[Q]`** | `PSR-BRW-030`, `PSR-BRW-004` |
| **FIS Astec Analytics** | 15 months instant; daily from 2005 via academic channel | — | **`[Q]`** | `PSR-BRW-032` |
| iBorrowDesk | ~1 year; *"not point in time and data quality is questionable"* | — | free | `PSR-BRW-039` |

**Three things that change the shape of Phase 3C:**

**1. ORTEX's advertised 16.6-year backtest is a trap.** The home page shows *"Backtest 4 Jan
2010 to 25 Aug 2026 (16.6 years)"* (`PSR-BRW-016`). That is the **stock-scores** backtester,
not the securities-lending series. Reading it as cost-to-borrow depth would be a material
error, and it is exactly the sort of thing a plan built on marketing pages would have got
wrong.

**2. ORTEX's structure, not its price, may be the obstacle.** Per-stock endpoints accept a date
range, but `/short_interest/ctb/all/` and `/index/short_ctb` take a **single `date`**
(`PSR-BRW-008`, `PSR-BRW-007`). A broad-universe historical panel therefore costs one call per
trading day — roughly 250/year, ~1,750 for seven years — or one call per ticker. ORTEX does not
document what a credit buys, so the Quant tier's 10,000 credits cannot be converted into a
feasible backfill volume. **Credit economics rank ahead of depth as the open question.**

**3. S3 Partners on AWS Data Exchange is the surprise worth checking first.** A vendor-authored
listing stating *"available free of charge"*, coverage since 2015, and *"All historical
revisions"* (`PSR-BRW-023`, `PSR-BRW-024`) is either a materially better answer than anything
else in this table or a limited-sample listing that reads better than it is. Establishing which
costs nothing and is the highest-value item in Phase 3C after the IBKR checklist.

#### Revised Phase 3C ordering

The evidence changes the order of work, and cheapest-first happens to also be
most-promising-first:

| Step | Action | Cost |
|---|---|---|
| 1 | **Establish `FEE_RATE` historical depth** via the TWS API — *requires A6; no broker interaction under this plan* | $0 |
| 2 | **Verify the S3 Partners AWS Data Exchange listing** — genuinely free and broad, or a sample? | $0 |
| 3 | Orbisa premium via the IBKR dashboard — 12 months, day resolution, UI-only | $12.99 |
| 4 | ORTEX — resolve credit economics **and** depth before committing | $149/mo |
| 5 | Institutional | `[Q]` |

Steps 1 and 2 cost nothing and may settle the question. Revision 1 skipped straight to step 4
and called it the cheapest valid option, which was wrong twice over.

> **Current IBKR availability MUST NOT be represented as historical borrow availability**, and
> short backtests remain **forbidden** until a source qualifies (ADR-0005 §15). Neither
> statement depends on how the IBKR question resolves.

### 2.10 Classification and benchmarks (domain J)

Vendor taxonomy with history if it exists; SEC SIC free but coarse; GICS licensed. ETF proxies
for benchmark and sector-relative returns, which sidesteps index licensing entirely and is
adequate for residual momentum. **Static-only classification is acceptable for paper research
and must carry `CLASSIFICATION_STATIC`** — not silently used.

### 2.11 Research-source metadata (domain K)

Free from EDGAR; vendor-supplied for transcripts. **Phase-deferred**: schema now, population
when the AI layer is authorized. No purchase implied.

---

## 3. Tiering

### Free, or already owned
`SEC EDGAR` (public domain, redistributable subject to a trademark carve-out — `PSR-SEC-001`,
`PSR-SEC-002`) · `LEAN market-hours-database` · `exchange_calendars` ·
**`QuantConnect cloud free tier`** (cloud only — `PSR-QC-006`) · IBKR *current* borrow · ETF
benchmark proxies · possibly `S3 Partners via AWS Data Exchange` (`PSR-BRW-023`, unverified in
practice)

### Practical individual / low-cost
`Sharadar Direct` **$9–$29/mo** · `EODHD` **$19.99–$99.99/mo** · `Massive` **$29–$199/mo** ·
`Norgate` **$270–$787.50 / 12 months** · `ORTEX` **$49–$149/mo** (+ API tier) ·
`Intrinio` **$150/mo** (no estimates)

### Paid, and formerly mistaken for free
**`QuantConnect US Equity Security Master` $600/yr · `AlgoSeek US Equities` daily bulk
$2,136/yr + $600/yr updates · LEAN CLI requires a paid organization tier**
(`PSR-QC-017`, `PSR-QC-018`, `PSR-QC-020`, `PSR-QC-011`)

### Institutional / quote-only
`FactSet Estimates PIT` · `LSEG I/B/E/S` · `Zacks Data` · `S&P Global Securities Finance` ·
`EquiLend DataLend` · `FIS Astec` · `Wall Street Horizon` · professional `Sharadar` via Nasdaq
Data Link — all **`[Q]`**

### Ruled out
`WRDS` — academic and non-commercial use only (`PSR-EST-034`) ·
`Databento` — wrong shape for a 2–30 day horizon (`PSR-DBN-013`) ·
`Norgate` as security master — no historical ticker mapping (`PSR-NRG-012`) ·
`Intrinio/Zacks` as a PIT estimates source — current consensus plus fixed lookbacks only
(`PSR-EST-010`, `PSR-EST-011`) ·
any current borrow snapshot presented as history ·
broker-supplied market data as a ranking source (ADR-0002 §13)

---

## 4. Cost scenarios

**Revision 1 quoted scenario A's price while describing scenario B/C's capability.** That is
the error §12 of [ADR-0005](../decisions/ADR-0005-point-in-time-data-architecture.md)
corrects.

All figures are Quant Researcher tier — the cheapest that can use the LEAN CLI at all
(`PSR-QC-011`). **The tier's own price is `[U]`** (`PSR-QC-035`) and must be added to every
row below.

### Scenario A — Sharadar-only local foundation

| Item | First year | Recurring |
|---|---|---|
| Sharadar Bundle @ $29/mo | $348 | $348/yr |
| SEC EDGAR | $0 | $0 |
| LEAN calendars, `exchange_calendars` | $0 | $0 |
| QuantConnect **cloud** free tier — spot cross-checks only | $0 | $0 |
| **Total** | **~$348** | **~$348/yr** |

Cross-provider checks (§7 of [data-quality-plan.md](data-quality-plan.md)) **largely do not
run**. Every result carries `SINGLE_SOURCE_UNVERIFIED`. The free LEAN sample bundle is **not** a
cross-check: it contains **21 daily equity tickers and 26 map files** against ~27,500 covered
equities (`PSR-QC-029`, `PSR-QC-030`). Its documented purpose is to *demonstrate file format*
(`PSR-QC-010`).

### Scenario B — Sharadar + paid local security master

| Item | First year | Recurring |
|---|---|---|
| Scenario A | $348 | $348/yr |
| QuantConnect US Equity Security Master | **$600** | **$600/yr** updates |
| QuantConnect organization tier | **`[U]`** | **`[U]`** |
| **Total** | **~$948 + tier** | **~$948/yr + tier** |

Buys an independent corporate-action, delisting and ticker-history cross-check — the highest-
consequence identity risks. Price cross-check remains single-sourced.

### Scenario C — Sharadar + paid security master + paid local daily price history

| Item | First year | Recurring |
|---|---|---|
| Scenario B | $948 | $948/yr |
| AlgoSeek US Equities, **daily** bulk | **$2,136** | **$600/yr** updates |
| **Total** | **~$3,084 + tier** | **~$1,548/yr + tier** |

Full §7 reconciliation. Note the updates subscription is **resolution-independent**
(`PSR-QC-020`), so ongoing daily-resolution cost equals tick.

### Scenario C′ — by-ticker instead of bulk

Daily by-ticker is **one file per security covering full history at 100 QCC = $1**
(`PSR-QC-022`, `PSR-QC-004`). For a ~1,200-name Blueprint §4 universe that is roughly **$1,200
one-time** plus the $600/yr security master — materially cheaper than $2,136/yr bulk, at the
cost of not covering delisted names outside the chosen list, which is precisely the wrong
corner to cut for a survivorship control.

**Inference:** B is the defensible minimum if identity errors are the concern, and identity
errors are the ones that corrupt everything downstream silently. A is honest only while
`SINGLE_SOURCE_UNVERIFIED` is on every result.

### Blocking-domain costs

| | |
|---|---|
| PIT analyst revisions | **`[Q]`** — FactSet PIT, LSEG I/B/E/S, or Zacks direct |
| Borrow history | IBKR checklist first ($0); then S3/AWS (possibly $0); then ORTEX **$149/mo API Quant tier**; then institutional **`[Q]`** |

**No purchase is authorized.** Scenario selection is gate G1 / authorization A3, and the
licensing gate below comes first.

---

## 5. The licensing gate — read before authorizing anything

**New in revision 2, and it is not a formality: one clause directly constrains what this
repository may publish.**

### 5.1 Sharadar is personal-use only, and the terms are explicit

| Term | Claim id |
|---|---|
| *"This License is granted solely to natural persons for personal use."* | `PSR-SHD-047` |
| *"You may not use the Services or the Services Data (or any derivation of the Services Data) for professional, commercial, institutional, or organizational purposes of any kind."* | `PSR-SHD-048` |
| *"This License is not available to legal entities or institutions."* | `PSR-SHD-052` |
| *"You may not publish, disseminate, re-distribute or share the Services Data."* | `PSR-SHD-055` |
| *"Commercial and institutional users should obtain data through Nasdaq."* | `PSR-SHD-063` |
| Within 30 days of termination, delete all copies; derived works that cannot reproduce the data may be kept | `PSR-SHD-061` |

**The good news, and it is genuinely good:** Sharadar's FAQ answers the exact question this
project raises — *"Personal Use covers individuals using the data for their own purposes:
research, backtesting, and **automated trading of their own account with no external clients
or money managed for others**"* (`PSR-SHD-014`).

**The caveat that keeps this a gate:** that sentence is in an FAQ, not in the licence, and the
Terms contain no equivalent carve-out. A reseller's summary states a Professional licence is
required if you manage others' money, work in finance, are compensated for analysis, operate as
a business, **or collaborate with others** (`PSR-SHD-069`, `[V2]`). "Collaborate with
others" is not a remote concern for a repository that is **public for collaboration**
(CLAUDE.md §3).

### 5.2 The clause that constrains this repository directly

> *"To the extent that you conduct any sort of testing or evaluation of the Services or the
> Services Data for purposes of determining usability or fitness for purposes intended, the
> conclusions arrived at related to the value, usability or fitness for purpose, or any other
> attributes of the Service or the Services Data shall not be published in any way."*
> — `PSR-SHD-059`, restated as *"You may not publish evaluations of this data without
> permission"* (`PSR-SHD-060`).

**This is exactly what Phase 3A/3B's provider tests P1–P8 produce.** A published data-quality
report saying "Sharadar's revision chronology is incomplete" is a published evaluation of
fitness for purpose. So:

- **Provider-test results, cross-provider reconciliation output and data-quality reports stay
  under `.runtime/` and are not committed** while the repository is public and this is
  unresolved ([data-quality-plan.md](data-quality-plan.md) §9,
  [implementation-plan.md](implementation-plan.md) §1.3).
- **This document is not covered by that clause.** It quotes public documentation, published
  prices and licence terms, and evaluates no vendor's *data* — because no vendor's data has
  been obtained. The review's own instruction stands: public-document planning comparisons may
  remain, with sources cited.

### 5.3 What must be obtained in writing before A3

1. **Personal automated trading of the owner's own funds** — confirm the FAQ position
   (`PSR-SHD-014`) binds, given the Terms do not repeat it.
2. **Future entity / professional / micro-live use** — what triggers the Professional licence,
   and what it costs (`[Q]`, `PSR-SHD-071`).
3. **Publication of empirical vendor-quality evaluations in a public repository** — permission,
   or a confirmed boundary (`PSR-SHD-059`).
4. **Retention and deletion after termination** — what "cannot reproduce the Services Data"
   permits us to keep (`PSR-SHD-061`).

Until all four are answered: **do not purchase, do not credential, do not publish empirical
conclusions derived from subscribed data, keep vendor payloads out of Git.**

### 5.4 Other licences

| Provider | Constraint | Claim id |
|---|---|---|
| **QuantConnect CLI data** | *"Display or distribution of data obtained through CLI API Access is not permitted … individual or internal employee's use … cannot be manipulated for transmission or use in other applications."* | `PSR-QC-016` |
| **QuantConnect security master** | *"designed to be used in the LEAN Engine and cannot be consumed another way"* | `PSR-QC-027` |
| **EODHD** | pricing-page plans are *"intended for personal use only as commercial use requires a more thorough licence"*; commercial plans $399–$2,499/mo | `PSR-EOD-020`, `PSR-EOD-003` |
| **Massive** | individual plans marked individual/non-professional; Business $2,499/mo | `PSR-MSV-006` |
| **Databento** | no licence needed for historical (>24h); real-time needs one if professional or redistributing | `PSR-DBN-003`, `PSR-DBN-004` |
| **WRDS** | academic and non-commercial only; redistribution prohibited | `PSR-EST-034`, `PSR-EST-036` |
| **SEC** | public information, redistributable, trademark carve-out | `PSR-SEC-001`, `PSR-SEC-002` |
| Identifiers | CUSIP/ISIN licensed; FIGI open. **Key on internal `security_id`**, never on a licensed identifier | — |

**Exchange market-data entitlements** are separate from any vendor subscription. V1 research is
end-of-day and avoids this; it re-enters at micro-live.

---

## 6. What must be re-verified before any purchase (A3)

1. Every price in §4, on the vendor's own page, on the day of purchase — the register's
   maintenance rule.
2. **The QuantConnect organization tier price** — `[U]`, and it sits underneath every scenario
   B/C figure.
3. **P1** — whether Sharadar `lastupdated` means "first appeared" or "last changed"
   (`PSR-SHD-022` says the latter, so `provider_available_time` is likely unobtainable and
   the dataset resolution becomes `EXCLUDE`, `BOUND` or `DOWNGRADE`). **`BOUND` is the likely
   outcome**, and it is the safe one: it pins provider availability to the day we first saw
   the row, so a vendor backfill cannot become historically admissible.
4. **P6** — the known-restatement test, against real data, notwithstanding that `PSR-SHD-018`
   and `PSR-SHD-019` already tell us the answer.
5. **P3** — whether Sharadar `ACTIONS` carries an announcement timestamp.
6. **SEC EDGAR field names and fair-access requirements** against the live API — every EDGAR
   claim here is `[V2]`.
7. **The S3 Partners AWS Data Exchange listing** — is it genuinely free and broad, or a sample?
8. **ORTEX credit economics and historical depth**, before any Phase 3C commitment.
9. **The four licensing questions in §5.3**, before the system trades real money.
