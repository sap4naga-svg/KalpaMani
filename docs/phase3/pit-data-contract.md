# The KalpaMani Point-in-Time Data Contract

**Status: PROPOSED — planning only.** Normative wording ("must", "fails closed") describes
the contract being proposed, not behaviour that exists. Nothing here is implemented.

Governed by [ADR-0005](../decisions/ADR-0005-point-in-time-data-architecture.md).

---

## 1. The one rule

> **Every research, scanning and backtest query returns only those records whose
> `source_available_time` is at or before the query's `as_of_time`.**

Everything else in this document is either a definition needed to make that sentence
unambiguous, or a rule for a case where the sentence is hard to honour.

The second rule is the one that makes the first one true in practice:

> **A record whose availability time cannot be established is not point-in-time. It is
> either excluded, or admitted only under an explicitly documented conservative lag.
> It is never admitted on the assumption that it was probably available.**

## 2. Terminology — exact meanings

These terms are used with exactly these meanings throughout Phase 3. Where a vendor uses one
of these words differently, the vendor meaning is mapped at ingestion and the vendor word is
not propagated.

| Term | Meaning | Example |
|---|---|---|
| `observation_time` | The instant the *fact* was true or measured in the world. | a trade printed at 15:59:58 ET |
| `effective_date` | The business date to which a fact applies; a **date**, not an instant. | a split effective 2024-06-10 |
| `source_publish_time` | When the **source** says it published. Vendor- or issuer-asserted. | a press release stamped 16:05 ET |
| `source_available_time` | **The governing field.** When KalpaMani could first have acted on it. Derived, never copied. | 16:05 ET release becomes available 16:05 ET |
| `ingestion_time` | When *we* first received the record. Always known, never a substitute for availability. | our fetch at 2026-08-26T02:14Z |
| `valid_from` | Start of the interval over which this version of the fact is the current one. | |
| `valid_to` | End of that interval; open-ended (`NULL`) for the current version. | |
| `revision_sequence` | Monotonic integer per logical fact. `0` is the original observation. | a restatement becomes `1` |
| `as_of_time` | The caller cutoff. **Mandatory on every historical query.** | |
| `source_id` | Stable identity of the originating document or feed record. | an EDGAR accession number |
| `vendor_record_id` | The vendor row identity, retained for reconciliation, never branched on. | |
| `dataset_version` | Identity of the curated build a result came from. | `gold/2026.08.26.1` |

**`source_available_time` is the only field the query contract reads.** `source_publish_time`
is an input to deriving it, and is frequently absent, wrong, or expressed in an ambiguous
timezone — which is exactly why the two are separate fields rather than one.

This mirrors [ADR-0002](../decisions/ADR-0002-broker-adapter-and-brokerage-boundary.md) §4:
vendor identifiers are *carried* for reconciliation and audit, never *branched on* by logic
above the boundary.

## 3. The temporal model

Two independent time axes, deliberately not collapsed into one:

```
VALID TIME     -- when the fact was true in the world
                  (effective_date, observation_time, fiscal period)

DECISION TIME  -- when KalpaMani could have known it
                  (source_available_time)
```

A query fixes decision time at `as_of_time` and is then free to range over valid time. That
is the whole mechanism:

```sql
SELECT ...
WHERE source_available_time <= :as_of
  AND effective_date BETWEEN :start AND :end
```

A restatement does not modify the original row. It is a **new row** for the same logical fact
with a higher `revision_sequence` and a later `source_available_time`. A backtest at a date
before the restatement sees the original; one after sees both and takes the latest
admissible. Nothing is ever updated in place — which is what makes defect class 7 (silent
history rewriting) structurally impossible rather than merely discouraged.

## 4. Deriving `source_available_time`

In priority order. The first rule that applies, wins.

| # | Situation | `source_available_time` |
|---|---|---|
| 1 | Authoritative machine timestamp exists (e.g. a filing acceptance datetime) | that timestamp, converted to UTC |
| 2 | Vendor supplies a publication timestamp **with** an unambiguous timezone | that timestamp, converted to UTC |
| 3 | Vendor supplies a publication **date** only | end of that date in the venue timezone **plus conservative lag** (§6) |
| 4 | Vendor supplies neither, but the record is tied to a session (e.g. a daily bar) | the session official close, plus the vendor stated publication lag |
| 5 | None of the above | **the record is not point-in-time.** Excluded, or admitted only under an explicitly documented and version-controlled lag |

Rule 5 is the one that matters. "The vendor gave us history, so it must be historical" is the
reasoning that produces look-ahead, and it is the same shape of reasoning
[BLUEPRINT_ERRATA](../architecture/BLUEPRINT_ERRATA.md) E-001 already caught once in a
different domain: an assumption about an external system that nobody had tested.

## 5. Hard cases, and what the contract does about each

### 5.1 Late-arriving data
A record arrives whose `source_available_time` precedes `ingestion_time` by more than the
dataset declared latency budget. **Accepted, but flagged.** It is stored with its true
availability time so history stays correct, and a `data_quality_issue` of severity `WARNING`
is raised. If the lateness exceeds the freshness bound of a dataset used for **live**
decisions, severity escalates to `BLOCKING` — stale data driving a live scan is a different
failure from stale data in a backtest.

### 5.2 Corrections
A vendor issues a corrected value for a record already stored. **New revision row.** The
original is never overwritten. If the correction carries no availability timestamp of its
own, it inherits `ingestion_time` — the conservative choice, since we demonstrably did not
have it earlier.

### 5.3 Restatements
A later filing restates an earlier period. **New revision row keyed to the same fiscal
period, carrying the restating filing acceptance time.** Research defaults to
*as-originally-reported* (the highest `revision_sequence` admissible at `as_of`), because
that is what a decision at the time would have used. Restated series remain available
explicitly and must never be the default — a factor computed on restated financials is a
factor computed on the future.

### 5.4 Vendor backfills
A vendor adds history it did not previously supply. This is the most dangerous case, because
it looks like ordinary new data. **Treated as new records with `ingestion_time = now`**, and
their `source_available_time` derived by §4 — which for genuinely old data means they *are*
admissible historically. The safeguard is that the bronze layer is immutable and
content-addressed, so a backfill is visibly a new acquisition and the previous state of the
world stays reconstructible. Any backfill that changes an already-published `dataset_version`
invalidates that version rather than mutating it.

### 5.5 Missing publication times
See §4 rule 5, and §6.

### 5.6 Conflicting vendor timestamps
Two sources disagree about when something was published. **Fail toward the later time.**
Record both, raise a `WARNING`, and use the later — the later time is the one that cannot
create look-ahead. Systematic disagreement between two sources on the same domain is a
`BLOCKING` issue, because it means at least one of them is wrong about something structural.

### 5.7 Timezone normalization
Everything is stored in **UTC**, as an aware instant. Local wall-clock times are never stored
without an offset. Market-facing logic converts to `America/New_York` at the edge and nowhere
else. `effective_date` and other business dates stay **dates** and are never silently
promoted to midnight-anything — a date is not an instant, and pretending otherwise is how a
fact arrives hours early.

### 5.8 Market-session dates versus calendar dates
A trading session is identified by its **session date from the exchange calendar**, not by
the UTC calendar date of any instant within it. These differ routinely (a 20:00 ET print is
the next UTC day) and the difference is a full day of look-ahead if confused. All bar and
session joins key on session date, sourced from the calendar domain, never derived by
truncating a UTC timestamp.

### 5.9 After-hours announcements
An announcement at 16:05 ET is available at 16:05 ET — **not** at the next open, and **not**
on the session date that just ended. The contract stores the true instant. What downstream
logic may *do* with it is a strategy decision (Blueprint §5.3: PEAD enters after the event),
not a data-layer one. The data-layer obligation is to refuse to move it.

### 5.10 Weekend and holiday publication
Publication does not require an open market. A Saturday 8-K is available Saturday. The first
*actionable* session is a separate, derived quantity (`next_tradable_session`), computed from
the calendar and never conflated with availability.

### 5.11 Daylight-saving transitions
US and EU DST shift on different dates; the gap weeks are where naive conversions break.
Rules: store UTC; convert with a real tz database (`zoneinfo`), never a fixed offset; never
hardcode `-05:00` or `-04:00`; treat 02:00–03:00 local on a spring-forward date as
non-existent, and 01:00–02:00 on a fall-back date as ambiguous, resolving ambiguity to the
**later** (post-transition) instant, consistent with §5.6.

Half-days and early closes are handled by the calendar domain, not by assumption — the same
correction [ADR-0004](../decisions/ADR-0004-deterministic-order-identity-idempotency-and-execution-lifecycle.md)
§14 already had to make once, when a hardcoded 15:30 bound would have permitted an entry one
minute before a 13:00 early close.

## 6. The conservative-lag policy

Where availability cannot be established exactly, a **documented, version-controlled,
per-domain lag** applies. A lag is a declared approximation, not a default — it is recorded
in configuration, carried in the dataset version, and reported with every result that
depended on it.

| Domain | Proposed lag when exact timing is unknown | Rationale |
|---|---|---|
| daily OHLCV | session close + 30 min | consolidated tape settles after the close |
| corporate actions | announcement date + 1 session | announcement time rarely published |
| fundamentals from filings | **none** — the acceptance datetime is authoritative | exact, machine-generated |
| fundamentals from a vendor with no filing link | filing date + 1 session | vendor processing lag unknown |
| earnings announcement, no verified time | **next session open** after the reported date | refuses to assume before-market |
| analyst estimate snapshots | snapshot date + 1 session | consensus files are end-of-day products |
| borrow availability / fee | **no lag is acceptable** — see below | |
| classification changes | effective date + 1 session | |

**Borrow is deliberately absent a lag.** There is no conservative lag that turns *current*
borrow data into *historical* borrow data; the value simply did not exist for that date. A
lag can only correct a timing error, never manufacture a missing observation. That is why
borrow is a Phase 3C qualification gate and not a lag-policy row.

Every lag applied is recorded in the research manifest
([reproducibility-and-provenance.md](reproducibility-and-provenance.md)). A result that
depended on an assumed lag is labelled as such and may not be reported as point-in-time
without that qualifier.

## 7. Fail-closed rules

Consistent with ADR-0004 §5 — *"It never assumes 'no record' means 'nothing happened'"* — the
data layer inherits the same posture.

The following are errors, not warnings, and abort the query rather than returning a degraded
result:

1. `as_of_time` absent from a historical query.
2. `as_of_time` later than the dataset build time.
3. A dataset whose declared `source_available_time` derivation is `UNKNOWN` participating in a
   point-in-time query.
4. A requested `as_of` earlier than the dataset declared coverage start.
5. A `BLOCKING` data-quality issue open against any dataset the query touches.
6. A universe query for a date with no `universe_membership` snapshot.
7. A schema version unrecognised by the reading code.
8. A checksum mismatch between a curated table and the bronze artifacts it declares.

Rule 4 deserves emphasis. **An empty result and a refusal are different answers**, and a data
layer that returns the first when it means the second will produce a backtest that looks
merely unprofitable rather than broken.

## 8. Universe queries and survivorship

`get_security_universe(as_of)` returns membership **as recorded for that date**, from a
stored snapshot. It is never recomputed from current data, and never derived by filtering
today listed securities.

Three consequences, all mandatory:

- A security delisted before `as_of` **is absent**. A security delisted after `as_of` but
  active then **is present**, including its subsequent delisting.
- Eligibility thresholds (price, market cap, ADDV, history length, exchange) are evaluated
  **using data admissible at that date**, not current data.
- The snapshot records the *version of the eligibility rule* that produced it. Changing the
  rule produces a new universe version; it does not retroactively change history.

Blueprint §4 thresholds — NYSE/NASDAQ common stock, price > $10, cap > ~$1.5B, ADDV > ~$25M,
> 250 days of history — are the initial rule. They are parameters of a versioned definition,
not constants in code.

## 9. The anti-lookahead query interface

Every historical accessor takes an explicit `as_of`. There is no default, no `latest`
convenience, and no overload without it.

```python
get_security_universe(as_of)                                        -> UniverseSnapshot
get_price_history(security_id, start, end, adjustment_mode, as_of)  -> BarSeries
get_fundamental_snapshot(security_id, period, as_of)                -> FundamentalFact
get_estimate_snapshot(security_id, estimate_period, as_of)          -> EstimateSnapshot
get_revision_history(security_id, start, end, as_of)                -> RevisionSeries
get_earnings_event(security_id, event_id, as_of)                    -> EarningsEvent
get_borrow_snapshot(security_id, as_of)                             -> BorrowSnapshot
get_classification(security_id, as_of)                              -> Classification
```

Enforced structurally, by test, in the manner ADR-0004 §10 already uses for the execution
boundary — *"Enforced by test, not convention"*:

- **`as_of` is required and has no default.** A static test asserts that no accessor in the
  PIT package declares `as_of` with a default value.
- **No `latest` path exists in research code.** A static scan forbids the identifiers
  `latest`, `current`, `most_recent` and `today` in the research and backtest packages. Live
  operation reads current data through a *separately named* live interface that cannot be
  called from backtest code.
- **`adjustment_mode` is required and explicit** — `RAW` or `ADJUSTED_AS_OF`. There is no
  implicit adjustment. Adjustment factors are themselves point-in-time: a split that had not
  been announced at `as_of` has not adjusted anything.
- **Results carry their provenance.** Every return value carries the `dataset_version`, the
  `as_of`, and the set of lags applied. A result that cannot say where it came from is not a
  result.

### 9.1 Live versus historical

```
kalpamani.data.pit     historical, as_of mandatory     usable by research and backtest
kalpamani.data.live    current, as_of forbidden        usable by live scanning only
```

Two packages, not one package with a flag. A flag is a thing that can be set wrongly; a
missing import is a thing that fails at test time. Research code importing `data.live` is a
static-test failure, in the same shape as ADR-0004 §10 rule that strategy modules cannot
import execution.

## 10. How LEAN consumes this

Blueprint §26 and ADR-0002 §13 impose the constraint: broker-supplied market data may be used
for operational verification, and is **never** the basis for universe ranking, backtests or
any performance claim.

Proposed arrangement:

```
PIT layer (authoritative)
    -> exports versioned, date-keyed files
        -> LEAN consumes them as custom data / universe files
            -> LEAN IBKR feed is used ONLY for live execution reality
```

Specifically:

- **Universe selection in LEAN reads an exported historical membership file keyed by session
  date.** It does not query a live universe API, and does not filter a current list. This is
  the single highest-risk integration point for survivorship leakage.
- **Fundamental, estimate and event data reach LEAN as custom data with explicit availability
  times**, so LEAN event scheduling honours them.
- **Price data for backtests comes from the curated layer**, cross-validated against LEAN
  bundled equity data as an independent check (see
  [data-quality-plan.md](data-quality-plan.md)). Disagreement is a quality issue, not
  something to silently prefer one side of.
- **IBKR delayed or live data is never written into the research store.** Phase 1 already
  established the pattern — SPY delayed data proved connectivity and nothing else.

The export step is deliberate. It means the inputs to a backtest are a **materialised,
versioned, checksummed artifact** rather than the live result of a query that might behave
differently tomorrow — which is the difference between a reproducible result and a result
that happened to reproduce.
