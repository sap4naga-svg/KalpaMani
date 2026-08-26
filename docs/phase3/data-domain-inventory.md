# Phase 3 — Data Domain Inventory

**Status: PLANNING.** Nothing here is implemented or purchased.

Each domain states what is needed, what makes it point-in-time, the concrete failure mode if
it is wrong, and its gap classification. Classifications are collected in §12 and are the
input to the Phase 3A/3B/3C split in [implementation-plan.md](implementation-plan.md).

Classification vocabulary, used exactly as defined:

| Class | Meaning |
|---|---|
| **BLOCKING** | Phase 3 cannot be accepted without it. |
| **ACCEPTABLE FOR LONG-ONLY V1** | Sufficient for the long book; insufficient for shorts. |
| **ACCEPTABLE ONLY FOR PAPER RESEARCH** | May inform research; may never support a live or micro-live claim. |
| **PHASE-DEFERRED** | Legitimately postponed to a later, named stage. |
| **NOT ACCEPTABLE** | Must never be used as a substitute for the real thing. |

---

## A. Security master

**Purpose.** A stable internal identity for a company/security that survives ticker changes,
exchange moves, mergers and delisting. Everything else joins to it.

| Required | Notes |
|---|---|
| `security_id` (internal, permanent) | Never a ticker. Tickers are recycled. |
| ticker history with `valid_from` / `valid_to` | The most common source of silent joins to the wrong company. |
| exchange / listing history | NYSE, NASDAQ, NYSE American; venue moves. |
| CUSIP / ISIN / FIGI or vendor ids where licensed | Redistribution-restricted; see licensing notes in [provider-evaluation.md](provider-evaluation.md). |
| entity relationships | Parent/subsidiary, successor after M&A. |
| listing start and end dates | |
| delisting date, reason, and terminal value handling | |
| symbol changes | Distinct from delisting. |
| M&A outcomes | Cash, stock, or mixed consideration. |
| security type | Common stock vs everything else. |
| common-stock eligibility flag | Blueprint §4 admits common stock only. |
| ADR identification | Blueprint §4 admits ADRs implicitly via the universe filters; must be *identifiable* either way. |
| ETF identification | Needed to exclude, and for benchmark series. |
| OTC / warrant / preferred / unit exclusion | Blueprint §4 initial exclusions. |

**PIT requirement.** Ticker→security mappings are time-varying and must be resolved at
`as_of`, never with today mapping.

**Failure mode.** `META` before 2022-06-09 was a different company. A backtest that joins by
ticker silently attributes one company history to another and produces a factor that never
existed. This class of error is invisible in aggregate statistics.

**Classification: BLOCKING.**

## B. Historical universe membership

**Purpose.** Which securities were eligible on each historical date, per Blueprint §4.

| Required | Notes |
|---|---|
| per-session membership snapshot | Stored, not recomputed. |
| price threshold (> $10) | evaluated on data admissible at that date |
| market-cap threshold (> ~$1.5B) | requires PIT shares outstanding — see F |
| ADDV threshold (> ~$25M) | rolling window ending at or before `as_of` |
| trading-history threshold (> 250 sessions) | |
| exchange eligibility | NYSE / NASDAQ |
| delisted securities present for dates they were listed | the survivorship control |
| `universe_definition_version` | changing the rule creates a version, not a rewrite |

**PIT requirement.** No step may consult current data. The market-cap threshold is the
subtle one: it needs shares outstanding *as known then*, not the current share count.

**Failure mode.** Using today universe for 2015 removes every company that has since failed.
Blueprint §19 lists controlling survivorship bias as a methodology requirement, and §17
already selects *survivorship-bias-aware* data for this reason.

**Classification: BLOCKING.**

## C. Market calendar

**Purpose.** The authority on what a session is. Consumed by nearly every other domain.

| Required | Notes |
|---|---|
| session dates per exchange | |
| holidays | |
| early closes / half days | ADR-0004 §14 already had to correct a hardcoded close assumption |
| trading halts (LULD, news pending) | affects bar validity, not session identity |
| regular vs extended hours boundaries | |
| timezone and DST rules | via `zoneinfo`, never fixed offsets |

**PIT requirement.** Historical calendars must be historical: exchange holiday schedules have
changed, and a future-dated calendar is itself a mild look-ahead when used to *schedule*.

**Failure mode.** Off-by-one session alignment across the whole dataset. Silent, systematic,
and it flatters momentum factors.

**Classification: BLOCKING.**

## D. OHLCV / market data

| Required | Notes |
|---|---|
| daily bars: open, high, low, close, volume | primary research resolution |
| **unadjusted** prices | the actual traded prices; the base for everything |
| **adjusted** prices, adjusted *as of* a date | adjustment is a PIT operation, not a static one |
| session date key | from C, never truncated from UTC |
| minute bars | only where a strategy demonstrably needs them; Blueprint §2 horizon is 2–30 days |
| trades / quotes | **not** justified for V1; excluded until a specific need is argued |
| VWAP where licensed | Blueprint §7 names execution optimization; not needed for V1 research |
| correction policy | vendors revise bars; revisions are rows, not updates |
| stale / missing bar handling | a halted or non-trading day is not a zero |

**PIT requirement.** `ADJUSTED_AS_OF` semantics. A price series adjusted with today split
factors embeds knowledge of every split since. For a momentum system this is not academic:
it changes ranks.

**Failure mode.** Backtesting on fully-adjusted prices makes past prices look smooth through
splits that had not happened. Combined with a price-threshold universe filter, it also
changes *membership*.

**Classification: BLOCKING.**

## E. Corporate actions

| Required | Notes |
|---|---|
| splits and reverse splits | ratio, announcement date, ex-date, effective date |
| ordinary dividends | declaration, ex, record, pay dates |
| special dividends | frequently mishandled by adjustment logic |
| spin-offs | the hardest adjustment case |
| mergers and acquisitions | terminal handling for the acquired security |
| rights offerings | |
| symbol changes | joins to A |
| delistings | joins to A |
| **announcement time distinct from effective date** | the PIT-critical field |

**PIT requirement.** An adjustment factor becomes admissible at **announcement**, not at
effective date, and certainly not retroactively. Defect class 4 in the
[charter](phase3-pit-data-foundation-charter.md) is exactly this.

**Failure mode.** A reverse split applied before it was announced changes a security price
level and therefore its universe eligibility — look-ahead that propagates into membership,
not just returns.

**Classification: BLOCKING.**

## F. Fundamentals

| Required | Notes |
|---|---|
| income statement, balance sheet, cash flow | |
| fiscal period and period end | |
| **filing date** | when the document was filed |
| **acceptance timestamp** | when it became publicly retrievable — the PIT field |
| form type | 10-K, 10-Q, 8-K, 20-F, 40-F |
| **as-originally-reported values** | the research default |
| restated values, as separate revisions | available explicitly, never default |
| trailing-twelve-month and quarterly derivations | derived from admissible rows only |
| **shares outstanding, point-in-time** | feeds market cap, feeds universe membership |
| market capitalization | derived; never a vendor current value |
| margins, growth, revision-adjacent metrics | Blueprint §6 composite inputs |
| source filing identity | accession number or equivalent |

**PIT requirement.** The distinction between as-reported and restated is the whole domain. A
restatement is new information at its own filing time and must not be visible before it.

**Failure mode.** Restated financials backfilled to the original period produce a fundamental
factor built on numbers nobody had. This is the classic silent look-ahead and it is
extremely flattering to quality and accrual factors.

**Classification: BLOCKING.**

## G. Earnings and guidance events

| Required | Notes |
|---|---|
| scheduled announcement date | forward-looking; needed for the "do not carry through earnings" rule (Blueprint §10.2) |
| **actual announcement timestamp** | the PEAD-critical field |
| before-market / after-market classification | derived from the timestamp, not asserted |
| reported EPS and revenue | |
| consensus **at announcement time** | requires H; see below |
| surprise calculation | a function of the above two — inherits their weakest link |
| guidance issued / changed | |
| transcript and filing availability times | feeds the AI Research Agent later (Blueprint §7.2) |

**PIT requirement.** PEAD (Blueprint §5.3) trades the post-announcement path. If the
announcement time is wrong by one session, the strategy is measured on the wrong window and
may appear to capture drift it actually captured as the event.

**Failure mode.** Assuming before-market when a release was after-market gives the strategy
a full session of hindsight.

**Reality.** Filing *acceptance* timestamps are exact and free. Press-release timestamps —
which usually precede the 8-K filing — are the accurate source of announcement time, and
accurate before/after-market classification is a specialist commercial product. Without one,
the [PIT contract](pit-data-contract.md) §6 lag applies: **next session open**.

**Classification: ACCEPTABLE FOR LONG-ONLY V1 under the conservative lag** — with the
recorded limitation that PEAD event-window precision is degraded, and that no PEAD
performance claim may be made without either verified announcement timestamps or an explicit
sensitivity analysis over the lag.

## H. Analyst estimates and revisions

| Required | Notes |
|---|---|
| consensus snapshots **through time** | not a current consensus |
| individual analyst estimate history where available | I/B/E/S detail-level |
| estimate period (FY1, FY2, Q1...) | |
| **revision timestamp** | the entire point of the domain |
| number of contributing analysts | |
| dispersion | |
| upgrades / downgrades | |
| price-target revisions | later, if justified |

**PIT requirement.** Blueprint §6 weights earnings/revision momentum at ~35–40%, and §9 names
*"earnings-revision velocity rather than static analyst ratings"* as a return-enhancement
mechanism. Velocity is a derivative with respect to time. **It cannot be computed from a
current snapshot at any price.**

**Failure mode.** Using current consensus as though it were historical is the single most
powerful look-ahead available in equity research — current consensus already reflects the
outcome.

> **A current consensus value with no historical snapshot or revision timing is NOT
> ACCEPTABLE for point-in-time backtesting.** It is not a degraded version of the right data;
> it is the answer sheet.

**Classification: BLOCKING for the revision sub-factor. NOT ACCEPTABLE to substitute current
consensus.**

The consequence is worked through in §12 and in
[provider-evaluation.md](provider-evaluation.md): the composite is built from its
PIT-available components, and the revision sub-factor is marked unavailable rather than
approximated.

## I. Short / borrow data

| Required | Notes |
|---|---|
| shortable availability (quantity) | historical, per session |
| hard-to-borrow status | |
| borrow fee / rate | historical, per session |
| rebate rate where applicable | |
| locate constraints | |
| **timestamp and historical snapshots** | the domain requirement |
| source / broker specificity | IBKR borrow is not a market-wide fact |
| SSR (short-sale restriction) state | Blueprint §12 requires it pre-execution |
| recall / buy-in events | Blueprint §12 names these as explicit operational states |

**PIT requirement.** Blueprint §12 requires borrow availability at signal time *and*
re-checked pre-submission, and a fee below a strategy threshold. Backtesting that requires
knowing both for every historical date.

**Failure mode.** A short backtest that assumes borrow was available and cheap will
systematically over-report short-side returns, because the names with the strongest short
signals are precisely the names that are expensive or impossible to borrow. The bias is not
random; it is adversarial.

> **Current IBKR availability MUST NOT be represented as historical borrow availability.**
> It is a different quantity, not a proxy.

**Classification: BLOCKING for the short family. NOT ACCEPTABLE to fabricate or proxy.**
Phase 3C exists to qualify this domain, and short research stays unauthorized until it
passes.

## J. Classification and benchmark data

| Required | Notes |
|---|---|
| sector and industry | Blueprint §6 needs sector-relative momentum |
| **classification history through time** | companies get reclassified |
| peer groups | Blueprint §5.4 Peer Catalyst Momentum (Phase 2 strategy, not V1) |
| index / benchmark returns | SPY-relative, residual momentum |
| classification change events | |

**PIT requirement.** Sector-relative and residual momentum are computed against a peer set. If
the peer set is today peer set, the residual is contaminated.

**Failure mode.** Moderate rather than catastrophic — sector drift is slow. But it biases
exactly the residual-momentum factor Blueprint §9 relies on to isolate stock-specific
strength.

**Licensing note.** GICS is licensed (S&P/MSCI). SIC codes are free from SEC filings but are
coarse and self-reported. A vendor sector taxonomy is the practical route; its *history* is
the part to verify.

**Classification: ACCEPTABLE FOR LONG-ONLY V1 with a vendor taxonomy, provided classification
history is stored and used at `as_of`. Static current classification is ACCEPTABLE ONLY FOR
PAPER RESEARCH**, and must be recorded as a limitation.

## K. Research-source metadata

**Purpose.** Provenance for the AI layer that arrives in a later phase. Blueprint §7.2 and
CLAUDE.md §7 both require it, so the data foundation should not have to be retrofitted.

| Required | Notes |
|---|---|
| filings, earnings releases, transcripts, guidance | document-level records |
| source URL / id | |
| **publication timestamp** | |
| document version | documents get amended |
| retrieval timestamp | |
| content hash | detects silent amendment |
| model version / prompt version fields | reserved now, populated when agents exist |

**PIT requirement.** CLAUDE.md §7: *"Every AI output requires timestamped source provenance,
model version and prompt version."* The document store must be able to answer "what text
existed at this time" or that requirement is unmeetable later.

**Classification: PHASE-DEFERRED** to Phase 3B for schema, populated when the AI layer is
authorized. The *schema* is designed now so it is not bolted on later.

---

## 12. Gap classification summary

The answer to "can Phase 3 proceed credibly without X":

| Gap | Classification | Consequence |
|---|---|---|
| **point-in-time analyst revisions** | **BLOCKING** for the revision sub-factor; substituting current consensus is **NOT ACCEPTABLE** | Blueprint §6 earnings/revision composite is built from PIT-available components only; the revision sub-factor is marked **NOT AVAILABLE** |
| **historical borrow availability and fees** | **BLOCKING** for the short family | Phase 3C gate; short research unauthorized until it passes |
| **delisted-security history** | **BLOCKING** | obtainable at low cost; see provider evaluation |
| **historical security-master changes** | **BLOCKING** | obtainable at low cost |
| **original and restated fundamentals** | **BLOCKING** | obtainable at low cost, and free from SEC filings |
| **exact earnings announcement timestamps** | **ACCEPTABLE FOR LONG-ONLY V1** under the next-session-open lag | PEAD event precision degraded; must be declared, and no PEAD claim without a lag sensitivity analysis |
| **classification history** | **ACCEPTABLE FOR LONG-ONLY V1**; static-only is **ACCEPTABLE ONLY FOR PAPER RESEARCH** | residual momentum mildly contaminated if static |
| **minute bars, trades, quotes** | **PHASE-DEFERRED** | not needed for a 2–30 day horizon |
| **peer groups (Blueprint §5.4)** | **PHASE-DEFERRED** | Peer Catalyst Momentum is a Blueprint Phase-2 strategy, not V1 |
| **AI research-source metadata** | **PHASE-DEFERRED** to schema-only | populated when the AI layer is authorized |

### The honest headline

**Phase 3 can proceed credibly, and produce a genuine point-in-time foundation, for the
long-only book — with one named factor degraded.**

**It cannot produce one for the short book at individual cost.** Blueprint §24 locks
direction as *"Long + short"*, and §12 makes short alpha a separate strategy family. Nothing
in this plan changes that decision, and no ADR is proposed to change it. What this plan does
is refuse to *simulate* it on data that does not exist:

- Phase 3A/3B deliver the long-side foundation.
- Phase 3C is the short-data qualification gate, and may be deferred.
- Until 3C passes, **short backtests are forbidden**, not merely discouraged, and no
  document may describe short support as available.

This is the same posture ADR-0004 §4a took toward an order whose fate was unknown: the
conservative reading, stated plainly, rather than an optimistic one that would read as
progress.
