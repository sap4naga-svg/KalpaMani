# Phase 3 — Implementation Plan

## STATUS: **PROPOSED — NOT STARTED, NOT AUTHORIZED**

This is a plan to be executed later, if approved. **No stage below has begun.** No
infrastructure has been created, no provider contacted, no credential requested.

---

## 1. Storage architecture

### 1.1 The layers

```
BRONZE / RAW          immutable vendor payloads, exactly as received
      |               content-addressed, never overwritten, never parsed in place
      v
SILVER / NORMALIZED   internal identifiers, UTC instants, normalised units
      |               deduplicated, revisions explicit, provenance retained
      v
GOLD / CURATED        point-in-time research tables
                      adjusted bars, historical universes, factor-ready snapshots,
                      earnings features, borrow-qualified short universe (when 3C passes)
```

**Bronze** holds the vendor payload byte-for-byte, gzipped, named by the SHA-256 of its
contents, with an `ingestion_run` row recording provider, dataset, requested range, retrieval
time, original schema version and hash. It is **append-only**. A re-fetch that returns
different bytes is a *new* artifact, not a replacement — which is what makes a vendor backfill
visible instead of silent ([pit-data-contract.md](pit-data-contract.md) §5.4).

**Silver** is where vendor semantics stop. Tickers become `security_id`. Local timestamps
become UTC instants with an `availability_derivation`. Vendor revision conventions become
`revision_sequence` rows. Nothing above silver knows which vendor supplied anything, except
through the provenance envelope it carries for audit.

**Gold** is what research reads, and it is **materialised and versioned** rather than computed
on demand — so a backtest input is an artifact with a hash, not the result of a query that may
behave differently next week.

### 1.2 Technology evaluation

| Option | Fit | Verdict |
|---|---|---|
| **Parquet on local disk** | columnar, compressed, partitioned by dataset/date, no server | **recommended** for silver and gold |
| **DuckDB** | reads Parquet natively, zero-install, single-file, strong analytical SQL, runs anywhere the repo runs | **recommended** as the research query engine |
| **PostgreSQL** | ADR-0001 and Blueprint §17 name it as the system database; correct for concurrent transactional state | **retained for operational state; not required by Phase 3** |
| **Object storage (S3-compatible)** | correct destination for bronze at scale | **deferred** — local disk now, path layout kept compatible |
| **LEAN-compatible export** | required for 3D | **yes** — an export step, not a storage layer |
| TimescaleDB | ADR-0001 lists as optional | not needed; the workload is analytical, not time-series ingest |

**Recommendation for the current Windows/Docker environment: Parquet files + DuckDB.**

Reasoning: Phase 3 is a single-node, single-writer, read-heavy analytical workload. DuckDB
needs no server, no container, no port, no credentials, and no operational surface — which
matters in a repository whose entire safety argument rests on there being fewer moving parts
than there could be. Parquet keeps the data portable, so migrating to PostgreSQL or object
storage later is a loader change, not a rewrite.

**This is explicitly not a replacement for PostgreSQL and does not contradict ADR-0001.**
ADR-0001 selects PostgreSQL as the database for *"features, signals, trades, audit state"* —
operational, transactional, concurrently written state. DuckDB here is a **query engine over
immutable research files**, which is a different job. PostgreSQL enters when there is
operational state to hold, and the `TradeStateStore` Protocol from ADR-0004 §5 is already the
pattern for that migration. If experience later shows the research layer genuinely belongs in
PostgreSQL, that is an ADR, not a quiet substitution.

### 1.3 Where it lives on disk

```
.runtime/data/bronze/<provider>/<dataset>/<ingest_date>/<sha256>.json.gz
.runtime/data/silver/<entity>/<partition>/*.parquet
.runtime/data/gold/<dataset_version>/<entity>/*.parquet
.runtime/data/catalog.duckdb
```

Under `.runtime/`, which is already git-ignored (`.gitignore:129`) and already the home for
everything that must never be committed.

**Vendor data must never be committed, and the reason is licensing rather than secrecy.**
Every low-cost provider examined forbids redistribution
([provider-evaluation.md](provider-evaluation.md) §5), and this repository is currently
**PUBLIC** (CLAUDE.md §3). A committed vendor payload would be a licence breach that is
world-readable and, as INC-0002 established at some cost, **a force-push does not undo it**.
Phase 3A adds an explicit `.gitignore` entry and a preflight check rather than relying on the
inherited one.

### 1.4 Package layout

```
src/kalpamani/data/
    pit/          historical accessors; as_of MANDATORY        <- research reads this
    live/         current accessors; as_of FORBIDDEN           <- live scanning only
    ingest/       vendor clients, bronze writers
    normalize/    silver transforms, identity resolution
    curate/       gold builders, universe construction
    quality/      deterministic checks
    contracts/    the schemas; no vendor knowledge
```

Enforced by static test, in the shape ADR-0004 §10 already uses: `strategies/`, `risk/`,
`portfolio/` and `research/` may import `data.pit` and `data.contracts` and **nothing else**;
research and backtest code may not import `data.live`; `data/` may not import `execution/` or
`broker/`.

---

## 2. Stage 3A — Security master, calendars, prices, actions, universe

| | |
|---|---|
| **Approval required first** | **A1**, plus **A2** before any credentialed fetch |
| **Vendor dependency** | Sharadar Bundle (proposed) · QuantConnect security master (owned) · LEAN market hours (owned) |
| **Cost** | **$29/mo** proposed; $0 until A2 |

**Inputs:** vendor API access under A2; LEAN toolchain already present.

**Deliverables**
1. `contracts/` — schemas 1–7, 16, 17, 18 from [conceptual-schema.md](conceptual-schema.md).
2. Bronze ingestion with content-addressed immutable writes and `ingestion_run` records.
3. Silver normalisation: identity resolution, ticker history, UTC/session normalisation.
4. Gold: `price_bar`, `corporate_action`, `market_session`, `ticker_history`, `listing`.
5. **Historical `universe_membership`**, constructed per Blueprint §4, versioned.
6. `data.pit` accessors: `get_security_universe`, `get_price_history`, `get_classification`.
7. Quality checks §3, §5, §6 and the temporal subset of §4 from
   [data-quality-plan.md](data-quality-plan.md).
8. Cross-provider reconciliation against the QuantConnect security master and LEAN calendars.

**Tests**
- `as_of` is positional and defaulted nowhere — static test over the package.
- No `latest` / `current` / `most_recent` / `today` identifier in research paths.
- Adjusted prices recomputed from raw + admissible actions reproduce a known series.
- Historical universe reconstruction is deterministic across rebuilds.
- Delisted securities appear in historical universes and vanish after delisting.
- Ticker-history overlap raises.
- `data/` cannot import `execution/` or `broker/`.

**Acceptance:** §6 criteria 1–5, 8, 9, 12 below.

**Risks**
| Risk | Mitigation |
|---|---|
| Sharadar PIT semantics differ from the datasheet | validate against a known restatement *before* building on it; the whole recommendation rests on this |
| No announcement timestamps in `ACTIONS` | apply the documented lag, record `CORPORATE_ACTION_ANNOUNCE_APPROXIMATED` |
| Personal-use licence does not cover future use | resolve at A2; see [provider-evaluation.md](provider-evaluation.md) §5.1 |
| Universe construction quietly uses current data | check 6.6 exists precisely for this |

## 3. Stage 3B — Filings, fundamentals, earnings timing, estimates

| | |
|---|---|
| **Approval required first** | **A3** before any estimates work |
| **Vendor dependency** | Sharadar `SF1`/`EVENTS` · SEC EDGAR (free) · estimates source **unresolved** |
| **Cost** | $0 incremental if Sharadar Bundle already held; estimates **[Q]** |

**Inputs:** 3A complete; SEC EDGAR access verified (currently **unverified** — see
[provider-evaluation.md](provider-evaluation.md) §1).

**Deliverables**
1. Schemas 8–12, 15.
2. EDGAR ingestion: `filing` records with **acceptance timestamps**, honouring SEC fair-access
   requirements (declared User-Agent, rate limiting).
3. `fundamental_fact` with as-reported default and restatements as revisions.
4. `earnings_event` with `announcement_time_confidence` and the derived session
   classification.
5. `get_fundamental_snapshot`, `get_earnings_event`.
6. `analyst_estimate_snapshot` and `analyst_revision` **schemas, unpopulated**, with the
   `ANALYST_REVISIONS_UNAVAILABLE` limitation wired into manifest emission.
7. Temporal quality checks §4 in full.

**Tests**
- A restatement is invisible before its filing acceptance time and visible after.
- `get_fundamental_snapshot` defaults to as-reported; restated requires an explicit request.
- An 8-K accepted at 21:30 UTC is not admissible at 21:29 UTC.
- `surprise_pct` is **null**, never zero, when consensus is unavailable.
- Sharadar and EDGAR agree on a sampled metric set, or a `WARNING` is raised.

**Acceptance:** §6 criteria 4, 6, 7, 10 below.

**Risks**
| Risk | Mitigation |
|---|---|
| EDGAR API differs from assumption | **verify before designing on it**; it is currently unverified |
| SEC rate limits throttle backfill | batch bulk files rather than per-company calls; budget wall-clock |
| Estimates gap never closes | that is an accepted outcome; the limitation token exists for it |
| Guidance extraction needs the AI layer | out of scope; deferred with the agents |

## 4. Stage 3C — Borrow history and short-data qualification

| | |
|---|---|
| **Approval required first** | **A4** — fund a source, or formally defer |
| **Vendor dependency** | **UNRESOLVED.** ORTEX (depth unverified) or institutional **[Q]** |
| **Cost** | **$149/mo** cheapest candidate, contingent; institutional **[Q]** |

**This stage is a qualification gate, not an implementation task.** It may legitimately end
in a recorded deferral.

**Deliverables — qualification**
1. A written determination of what historical borrow data is actually obtainable, at what
   depth, at what price, under what licence.
2. If a source qualifies: schema 13 populated, `get_borrow_snapshot` implemented, freshness
   check 4.6 active.
3. If none qualifies: a recorded deferral, `BORROW_HISTORY_UNAVAILABLE` permanently asserted,
   and the short family left unbuilt.

**Tests (only if a source qualifies)**
- Borrow snapshots are source-keyed and never merged across sources.
- A short position in a run whose limitations include `BORROW_HISTORY_UNAVAILABLE` is refused
  at manifest emission.
- Borrow data older than the freshness bound blocks rather than degrades.

**Acceptance:** §6 criterion 11 — which is a gate, not a checkbox.

**The rule that survives either outcome:** short backtesting stays **forbidden** until this
stage passes. Blueprint §24 keeps long+short as the locked target; this plan does not change
that and proposes no ADR to. It refuses to simulate the short half on data that does not
exist.

## 5. Stage 3D — LEAN integration, manifests, blocking gates

| | |
|---|---|
| **Approval required first** | — (covered by A1) |
| **Vendor dependency** | none |
| **Cost** | $0 |

**Deliverables**
1. Gold → LEAN export: date-keyed universe files, custom data with availability times.
2. LEAN universe selection reads the exported historical membership file. **This is the
   highest-risk integration point in Phase 3.**
3. Research manifest emission with the §4 preconditions from
   [reproducibility-and-provenance.md](reproducibility-and-provenance.md).
4. `BLOCKING` gating wired into the query layer, the backtest entry point and manifest
   emission.
5. A data-quality report per ingestion run.
6. `scripts/phase3_preflight.py`, in the shape of the Phase-1 and Phase-2 preflights: static
   checks, non-zero exit, run before anything else.

**Tests**
- A LEAN backtest reads from the PIT layer, never from a broker feed.
- IBKR data never reaches the research store.
- A backtest refuses to start with a `BLOCKING` issue open.
- A manifest is refused on a dirty working tree.
- Same manifest, rerun → identical `run_id` and identical result hash.

**Acceptance:** §6 criteria 13, 14, plus the adversarial fixtures.

---

## 6. Phase 3 acceptance criteria

Measurable, and each one fails a specific defect class rather than expressing a preference.

| # | Criterion | Method |
|---|---|---|
| 1 | **Historical ticker / delisting test** | Resolve a known ticker reassignment (e.g. a ticker reused by a different issuer) at dates before and after the change; both resolve to the correct, different `security_id`. |
| 2 | **Survivorship-bias test** | A universe snapshot for a date ≥8 years past contains securities delisted since, at a rate consistent with the era. Zero delisted members **fails**. |
| 3 | **Split / dividend adjustment test** | Adjusted series recomputed from raw + admissible actions matches an independently adjusted reference within tolerance, **and** differs from a today-adjusted series at dates before the split. |
| 4 | **Filing-publication timing test** | A filing is inadmissible one second before its acceptance time and admissible one second after. |
| 5 | **Restatement / revision test** | A company with a known restatement returns the original figure at an `as_of` before the restating filing, and both revisions after. |
| 6 | **Analyst-estimate as-of test** | With the gap open: any attempt to serve estimates raises rather than returning current values. If a source is later licensed: a snapshot query returns the consensus that stood at `as_of`, not the current one. |
| 7 | **Earnings-event timing test** | An after-market announcement is not admissible during the session that preceded it. |
| 8 | **Historical universe reconstruction test** | Rebuilding a historical snapshot from the same inputs and rule version is bit-identical. |
| 9 | **Stale-data rejection test** | A dataset past its freshness bound blocks live-facing queries. |
| 10 | **Deterministic dataset build** | Two builds from the same bronze artifacts produce identical `content_hash`. |
| 11 | **Borrow qualification test** | Either a qualified historical borrow source passes its tests, **or** the deferral is recorded and short research remains unauthorized. **Short research cannot be authorized by any other route.** |
| 12 | **LEAN reads the PIT layer** | A backtest sources universe, prices and fundamentals from gold exports; no broker data path is reachable from research. |
| 13 | **No current data in an earlier as-of query** | See adversarial fixtures below. |
| 14 | **Reproducibility test** | A manifest reruns to an identical result hash, or fails loudly naming the missing input. |

### 6.1 Adversarial fixtures

Deliberately constructed to *produce* look-ahead if the guarantee is broken. Each must fail
the pipeline, not pass it. A test suite that only proves the happy path is how ADR-0004 §20
shipped a sign bug behind 100% green tests — the fixture defaulted to the direction the broker
never sends.

| # | Fixture | Must |
|---|---|---|
| F1 | A fundamental row whose `source_available_time` is one day **before** its filing acceptance time | be rejected by check 4.2 |
| F2 | A restatement row with `source_available_time` earlier than the original it revises | be rejected by check 4.1 |
| F3 | A universe snapshot built from a current listing query | be caught by checks 6.3/6.4 |
| F4 | A price series adjusted with a split announced **after** `as_of` | differ from the correct series, and the correct path must not produce it |
| F5 | An earnings event stamped 09:00 ET on a day the release was 16:05 ET | change the PEAD window measurably, and be flagged by 4.5 |
| F6 | An estimate snapshot series with a non-monotonic `snapshot_time` | be rejected by check 4.4 |
| F7 | A borrow snapshot copied forward from a later date | be rejected by check 4.6 |
| F8 | A ticker mapped to two securities on one date | be rejected by check 6.1 |
| F9 | A bar whose session date was derived by truncating a UTC timestamp across a 20:00 ET print | be rejected by check 4.10 |
| F10 | A query with `as_of` omitted | fail to compile or raise — never default |
| F11 | A DST fall-back ambiguous instant stored unresolved | be rejected by check 4.9 |
| F12 | A short position in a run limited by `BORROW_HISTORY_UNAVAILABLE` | be refused at manifest emission |

**F4 deserves its own note.** It is the fixture most likely to pass accidentally, because an
adjusted series that embeds a future split still *looks* like a price series. The test must
assert a numerical difference against the correct as-of series, not merely that the query
returned something.

---

## 7. Sequence and dependencies

```
A1 -------> 3A --------> 3B --------> 3D --------> A5 (accept Phase 3)
      A2 ---^       A3 ---^      ^
                                 |
                    3C ----------+   (A4: fund, or defer)
                    gate: short research
```

3C is off the critical path by design. If borrow data is unaffordable, Phase 3 still
completes — as a long-only foundation with a recorded gap, which is a truthful outcome. It
does not complete as a system that claims short support.

## 8. Estimated effort

Blueprint §21 budgets 1–2 weeks for data feasibility and 2–3 for the data+factor foundation.
This plan covers the data half only.

| Stage | Estimate | Note |
|---|---|---|
| 3A | 1.5–3 weeks | universe construction and cross-validation dominate |
| 3B | 1–2 weeks | EDGAR ingestion is the bulk; estimates are blocked, not built |
| 3C | 2–5 days | qualification research, not implementation |
| 3D | 1–1.5 weeks | LEAN export and gating |

**Planning estimate, not a commitment.** Blueprint §21 already cautions that forward
validation and operational hardening cannot be compressed safely; the same applies here, and
the largest uncertainty is item 2 of §9 below.

## 9. Top risks

1. **Sharadar PIT semantics do not hold up under test.** The entire low-cost recommendation
   rests on the datasheet claim that data is time-indexed to the filing date with restatements
   separable. Validate it first, on a known restatement, before building anything on it. If it
   fails, the fundamentals domain reverts to SEC EDGAR alone — slower and narrower, but free
   and definitionally point-in-time.
2. **The estimates gap does not close.** Accepted and planned for. The cost is a degraded
   Blueprint §6 composite, declared rather than hidden.
3. **Borrow data stays unaffordable.** Accepted. V1 goes long-only with the short family
   recorded as unbuilt for lack of data.
4. **Silent look-ahead survives the checks.** The residual risk that matters. Mitigation is
   the adversarial fixtures plus a standing rule: **a result that improves unexpectedly is
   investigated before it is believed.**
5. **Licence scope changes under the system.** Personal-use terms fit a personal research
   project and may not fit what this becomes. Resolve at A2 and again before micro-live.

## 10. Explicitly not in this plan

> factor computation · strategy logic · ranking implementation · the portfolio and risk engine
> · AI Research and Challenger agents · order generation · any change to Phase-1 or Phase-2
> execution code · brokerage interaction of any kind · production cloud infrastructure ·
> PostgreSQL deployment · dashboards · alerting · the kill switch

Phase 4 is not authorized, not scoped here, and not begun.
