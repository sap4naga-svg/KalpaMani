# Phase 3 — Implementation Plan

## STATUS: **PROPOSED — NOT STARTED, NOT AUTHORIZED**

This is a plan to be executed later, if approved. **No stage below has begun.** No
infrastructure has been created, no provider contacted, no credential requested.

> **Revision 3 (2026-08-26).** Provider test P1 now records an `information_origin` per
> dataset and drives the `EXCLUDE` / `BOUND` / `DOWNGRADE` choice; four adversarial fixtures and
> two negative controls are added for origin eligibility; acceptance criteria 15 and 18 cover
> profile eligibility.
>
> **Revision 2 (2026-08-26).** Storage now reflects the adjusted-price decision
> ([contract §8](pit-data-contract.md)); provider tests now include the **revision-chronology
> qualification** and **provider-availability-semantics** tests that revision 1 assumed away;
> Phase 3C leads with an **IBKR qualification checklist** rather than a categorical dismissal;
> authorizations are renumbered A1–A7 to insert the **licensing gate (A2)** and the
> **information-set profile decision (A4)**; cost scenarios are enumerated rather than assuming
> a free cross-check.

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
GOLD / CURATED        point-in-time research artifacts, profile-keyed
                      RAW bars + corporate actions, historical universes,
                      factor-ready snapshots, earnings features,
                      keyed adjusted-bar cache artifacts,
                      borrow-qualified short universe (only when 3C passes)
```

**Gold holds raw bars, not adjusted ones.** Adjusted series are computed
([contract §8](pit-data-contract.md)) and materialise only as `adjusted_bar_artifact` rows
keyed by adjustment policy, information-set profile, `as_of_epoch`, corporate-action dataset
version, raw-bar dataset version and scope. Revision 1 listed "adjusted bars" here while the
schema said adjusted bars are never stored; that contradiction is resolved in favour of the
schema plus an explicitly keyed cache.

**Bronze** holds the vendor payload byte-for-byte, gzipped, named by the SHA-256 of its
contents, with an `ingestion_run` row recording provider, dataset, requested range, retrieval
time, original schema version, hash, and whether the run was a backfill. It is **append-only**.
A re-fetch returning different bytes is a *new* artifact, not a replacement — which is what
makes a vendor backfill visible instead of silent, and what lets the profile model
(§[contract 3.3](pit-data-contract.md)) decide what to do about it.

**Silver** is where vendor semantics stop. Tickers become `security_id`. Local timestamps
become UTC instants with an `availability_derivation`. Vendor revision conventions become
`revision_sequence` rows. Nothing above silver knows which vendor supplied anything, except
through the provenance envelope carried for audit.

### 1.2 Technology evaluation

| Option | Fit | Verdict |
|---|---|---|
| **Parquet on local disk** | columnar, compressed, partitioned, no server | **recommended** for silver and gold |
| **DuckDB** | reads Parquet natively, zero-install, single file, strong analytical SQL | **recommended** as the research query engine |
| **PostgreSQL** | ADR-0001 and Blueprint §17 name it as the system database; correct for concurrent transactional state | **retained for operational state; not required by Phase 3** |
| **Object storage (S3-compatible)** | correct destination for bronze at scale | **deferred** — local disk now, path layout kept compatible |
| **LEAN-compatible export** | required for 3D | **yes** — an export step, not a storage layer |
| TimescaleDB | ADR-0001 lists as optional | not needed; the workload is analytical, not time-series ingest |

**Recommendation for the current Windows/Docker environment: Parquet files + DuckDB.**

Phase 3 is a single-node, single-writer, read-heavy analytical workload. DuckDB needs no
server, no container, no port, no credentials and no operational surface — which matters in a
repository whose safety argument rests on there being fewer moving parts than there could be.
Parquet keeps the data portable, so migrating to PostgreSQL or object storage later is a loader
change, not a rewrite.

**This is not a replacement for PostgreSQL and does not contradict ADR-0001**, which selects
PostgreSQL for *"features, signals, trades, audit state"* — operational, transactional,
concurrently-written state. DuckDB here is a query engine over immutable research files, a
different job. If experience later shows the research layer belongs in PostgreSQL, that is an
ADR, not a quiet substitution.

### 1.3 Where it lives on disk

```
.runtime/data/bronze/<provider>/<dataset>/<ingest_date>/<sha256>.json.gz
.runtime/data/silver/<entity>/<partition>/*.parquet
.runtime/data/gold/<dataset_version>/<entity>/*.parquet
.runtime/data/gold/<dataset_version>/adjusted/<artifact_id>.parquet
.runtime/data/catalog.duckdb
```

Under `.runtime/`, already git-ignored (`.gitignore:129`) and already the home for everything
that must never be committed.

**Vendor data must never be committed, and the reason is licensing as much as secrecy.** Every
low-cost provider examined forbids redistribution, and several restrict publishing derived
analysis ([provider-evaluation.md](provider-evaluation.md) §5). This repository is currently
**PUBLIC** (CLAUDE.md §3). A committed vendor payload would be a licence breach that is
world-readable and, as INC-0002 established at some cost, **a force-push does not undo it**.
Phase 3A adds an explicit `.gitignore` entry and a preflight check rather than relying on the
inherited one. **Derived quality reports and research manifests built from subscribed data are
covered by the same rule** until gate G3 is settled.

### 1.4 Package layout

```
src/kalpamani/data/
    pit/          historical accessors; as_of + profile MANDATORY   <- research reads this
    live/         current accessors; as_of FORBIDDEN                <- live scanning only
    ingest/       vendor clients, bronze writers
    normalize/    silver transforms, identity resolution
    curate/       gold builders, universe construction, adjustment
    quality/      deterministic checks
    contracts/    the schemas; no vendor knowledge
```

Enforced by static test, in the shape ADR-0004 §10 already uses: `strategies/`, `risk/`,
`portfolio/` and `research/` may import `data.pit` and `data.contracts` and **nothing else**;
research and backtest code may not import `data.live` and may not reference `LATEST_RESTATED`;
`data/` may not import `execution/` or `broker/`.

### 1.5 Cost scenarios

Costs are **not** duplicated here. They live in one place —
[provider-evaluation.md](provider-evaluation.md) §4 — with a claim id per figure in
[provider-source-register.md](provider-source-register.md), so a reviewer can retrieve every
number. The scenarios themselves are:

| Scenario | Foundation | Cross-validation | Consequence |
|---|---|---|---|
| **A** | Sharadar-only local foundation | free/limited only — public reference data and any free-tier spot checks | cheapest; §7 cross-provider checks largely **do not run**; every result carries `SINGLE_SOURCE_UNVERIFIED` |
| **B** | Sharadar + **paid** local security master | independent corporate-action, delisting and ticker-history cross-check | closes the highest-consequence identity risks; price cross-check still single-sourced |
| **C** | Sharadar + **paid** local security master + **paid** local price history | full §7 cross-provider reconciliation | most defensible; highest recurring cost |

**Revision 1 assumed scenario C at scenario A's price**, by describing a local QuantConnect
cross-check as bundled. Correcting that is the point of §12 in
[ADR-0005](../decisions/ADR-0005-point-in-time-data-architecture.md): single-sourcing is a
legitimate choice, and implying verification while single-sourcing is not.

**No purchase is authorized.** Scenario selection is part of gate G1 (authorization A3), and
gate G3 (authorization A2, licensing) comes first.

---

## 2. Stage 3A — Security master, calendars, prices, actions, universe

| | |
|---|---|
| **Approvals required first** | **A1**; **A2** (licensing clarification) then **A3** (subscription) before any credentialed fetch |
| **Vendor dependency** | per the selected cost scenario (§1.5) |
| **Cost** | $0 until A3; see [provider-evaluation.md](provider-evaluation.md) §4 |

**Inputs:** vendor access under A3; LEAN toolchain already present.

**Deliverables**
1. `contracts/` — schemas 1–7, 7a, 16, 17, 18 from [conceptual-schema.md](conceptual-schema.md).
2. Bronze ingestion with content-addressed immutable writes, `ingestion_run` records, and
   backfill detection.
3. Silver normalisation: identity resolution, ticker history, UTC/session normalisation, and
   population of all four information times.
4. Gold: `price_bar` (**raw**), `corporate_action`, `market_session`, `ticker_history`,
   `listing`, plus the `adjusted_bar_artifact` builder.
5. **Historical `universe_membership`**, per Blueprint §4, versioned **and profile-keyed**.
6. `data.pit` accessors: `get_security_universe`, `get_price_history`, `get_classification`.
7. Quality checks §3, §4.1–§4.3, §4.5, §5, §6 from [data-quality-plan.md](data-quality-plan.md).
8. Cross-provider reconciliation **to the extent the selected scenario licenses it**, with
   `SINGLE_SOURCE_UNVERIFIED` emitted where it does not.

**Blocking provider tests — run before building on the data**

These are new in revision 2, and each one is a claim revision 1 accepted on a vendor's word:

| # | Test | If it fails |
|---|---|---|
| P1 | **Provider-availability semantics and origin.** Does the vendor update/`lastupdated` column mean "first appeared" or "last changed"? Verify against a row known to have changed. Record the dataset `information_origin` at the same time. | `provider_available_time` is unobtainable → the dataset resolution becomes `EXCLUDE`, `BOUND` or `DOWNGRADE` ([contract §3.3](pit-data-contract.md)), declared in configuration and reported in every manifest. Documentation already indicates the leading candidate means *last changed*, so `BOUND` is the likely outcome — which by construction keeps backfills inadmissible in the past. |
| P2 | **Delisted coverage is real.** Sample securities delisted 5, 10 and 15 years ago and confirm full history is present. | survivorship control fails; the domain reverts to another source |
| P3 | **Corporate-action announcement timing.** Does the dataset carry an announcement date/time distinct from ex-date? | `CORPORATE_ACTION_ANNOUNCE_APPROXIMATED` lag applies and is declared |
| P4 | **Classification history.** Are sector/industry changes historised, or is only the current value supplied? | `CLASSIFICATION_STATIC` limitation applies |
| P5 | **Adjusted/raw reconciliation.** Recomputing adjusted from raw + actions reproduces the vendor's adjusted series. | check 5.6 blocks the dataset |

**Tests**
- `as_of`, `profile` positional and defaulted nowhere — static test over the package.
- No `latest` / `current` / `most_recent` / `today` identifier in research paths.
- Profile ordering invariant holds on real data.
- Adjusted artifacts reproduce bit-identically from their keys; unkeyed adjusted series refused.
- Historical universe reconstruction is deterministic across rebuilds, per profile.
- Delisted securities appear in historical universes and vanish after delisting.
- Ticker-history overlap raises.
- `data/` cannot import `execution/` or `broker/`.

**Acceptance:** §6 criteria 1–5, 8, 9, 12, 15, 16.

**Risks**
| Risk | Mitigation |
|---|---|
| Vendor PIT semantics differ from the datasheet | P1–P5 run **first**; the whole low-cost recommendation rests on them |
| Provider availability unobtainable | `EXCLUDE`, `BOUND` or `DOWNGRADE`, all declared — never assumed, and never the withdrawn `DECLARE` |
| Single-source blind spots | `SINGLE_SOURCE_UNVERIFIED` on every affected result |
| Personal-use licence does not cover intended use | gate G3 / authorization A2 precedes purchase |
| Universe construction quietly uses current data | check 6.6 exists precisely for this |

## 3. Stage 3B — Filings, fundamentals, earnings timing, estimates

| | |
|---|---|
| **Approvals required first** | **A5** before any estimates work |
| **Vendor dependency** | fundamentals provider · SEC EDGAR · estimates source **unresolved** |
| **Cost** | see [provider-evaluation.md](provider-evaluation.md) §4; estimates are quote-only |

**Inputs:** 3A complete; SEC EDGAR access **verified** — it remains unverified from this
environment ([provider-source-register.md](provider-source-register.md)).

**Deliverables**
1. Schemas 8–12, 15.
2. EDGAR ingestion: `filing` records with **acceptance timestamps**, honouring SEC fair-access
   requirements (declared User-Agent, rate limiting).
3. `fundamental_fact` with all three revision views implemented and
   `revision_chronology_completeness` populated from the P6 test below.
4. `earnings_event` with both availability anchors, `announcement_time_confidence`, and the
   derived session classification.
5. `get_fundamental_snapshot`, `get_earnings_event`.
6. `analyst_estimate_snapshot` and `analyst_revision` **schemas, unpopulated**, with
   `ANALYST_REVISIONS_UNAVAILABLE` wired into manifest emission.
7. Temporal quality checks §4.4 in full.

**Blocking provider tests**

| # | Test | If it fails |
|---|---|---|
| **P6** | **Known-restatement qualification.** Take a company with a documented multi-step restatement. Confirm each intermediate revision is present with its own distinct availability time, and that a query at a date between two restatements returns the one then current. | `revision_chronology_completeness = FIRST_AND_LATEST_ONLY`; every dependent run carries `REVISION_CHRONOLOGY_INCOMPLETE`; `AS_KNOWN_AT_AS_OF` is a declared two-point approximation |
| P7 | **Filing-linkage.** Every fundamental row resolves to a filing with an acceptance timestamp. | the §9 vendor lag applies and is declared |
| P8 | **Earnings-timing fidelity.** Compare vendor announcement timing against 8-K acceptance times on a sample. | `EARNINGS_TIME_APPROXIMATED` |

P6 is the test revision 1 did not have. It is the difference between *claiming* point-in-time
fundamentals and *having* them, and it is blocking because a two-point approximation silently
returns the original figure for every date between two restatements.

**Tests**
- A restatement is invisible before its filing acceptance time and visible after.
- `AS_KNOWN_AT_AS_OF` returns a restatement already published at `as_of`;
  `ORIGINAL_FILING_ONLY` does not.
- `LATEST_RESTATED` is unreachable from research code (static), and refused at runtime.
- An 8-K accepted at 21:30 UTC is not admissible at 21:29 UTC.
- A **scheduled** earnings date announced weeks ahead is admissible and **not** blocked.
- `surprise_pct` is **null**, never zero, when consensus is unavailable.

**Acceptance:** §6 criteria 4, 6, 7, 10, 14.

**Risks**
| Risk | Mitigation |
|---|---|
| EDGAR API differs from assumption | **verify before designing on it**; currently unverified |
| SEC rate limits throttle backfill | prefer bulk files to per-company calls; budget wall-clock |
| Revision chronology incomplete | P6 detects it; the limitation token declares it |
| Estimates gap never closes | an accepted outcome; the token exists for it |

## 4. Stage 3C — Borrow history and short-data qualification

| | |
|---|---|
| **Approvals required first** | **A6** — fund a source, or formally defer |
| **Vendor dependency** | **UNRESOLVED** |
| **Cost** | see [provider-evaluation.md](provider-evaluation.md) §4 |

**This stage is a qualification gate, not an implementation task.** It may legitimately end in
a recorded deferral.

### 4.1 Step one: the borrow history KalpaMani can already reach

Revision 1 dismissed IBKR categorically and was wrong. IBKR documents **four** historical
borrow surfaces, and one of them is programmatic through the TWS API this system already
connects to ([provider-evaluation.md](provider-evaluation.md) §2.9):

> `reqHistoricalData` with `whatToShow=FEE_RATE` returns OHLC bars of the stock borrow fee
> rate, *"available in various units of duration up to the present moment"*
> (`PSR-IBK-010`, `PSR-IBK-034`).

**Its historical depth is documented nowhere** (`PSR-IBK-043`), and that single unknown decides
whether the short family is blocked by data or merely by effort.

**This plan does not and may not find out.** Establishing it means calling the broker, which is
broker interaction and requires **A6**. It is the first task of Phase 3C, not of planning.

The checklist, each item answered explicitly and recorded:

| # | Question | Why it decides the outcome |
|---|---|---|
| 1 | **`FEE_RATE` maximum depth** — how far back does a request actually return? | the decisive unknown; ten days is worthless, five years is transformative |
| 2 | Which **fields** are exposed — quantity, indicative rate, fee, rebate, lender count? | a rate without a quantity cannot size a short (`PSR-IBK-013`, `PSR-IBK-025`) |
| 3 | **Per-symbol or bulk?** `FEE_RATE` is per contract; SLB supports file upload (`PSR-IBK-020`, `PSR-IBK-029`) | a per-symbol path can still build a panel if the rate limit allows ~1,200 names |
| 4 | **Granularity** — intraday half-hour, daily, end-of-day? (`PSR-IBK-022`, `PSR-IBK-026`) | Blueprint §12 needs signal-time *and* pre-submission checks |
| 5 | **Delisted names** — does history survive delisting? | a borrow history that drops delisted names reintroduces survivorship at the worst possible point |
| 6 | **Revisions** — is the indicative rate ever restated after the day settles? (`PSR-IBK-033`) | decides whether `revision_sequence` is needed here |
| 7 | **Licensing** — what does IBKR permit this data to be used for? **No public page states it** (`PSR-IBK-044`) | absence of a stated restriction is not a grant |
| 8 | **Bucketing** — is the historical series exact, or bucketed like the live tick? (`PSR-IBK-011`) | a bucketed availability series cannot size a position |
| 8a | **Origin** — does the source stamp each observation with its own time (`PROVIDER_DERIVED`), or do we merely poll it (`SYSTEM_OBSERVED`)? | decisive: a `SYSTEM_OBSERVED` series is eligible **only** under `FORWARD_SYSTEM`, so it can support forward validation but **not** a historical short backtest, whatever its depth |
| 9 | Can it support **broad-universe historical short research**? | the actual question |

A **yes** to 1–8 and a **no** to 9 is a perfectly possible outcome, and it is not a failure of
the checklist — it is the finding. `borrow_snapshot.coverage_scope`
([conceptual-schema.md](conceptual-schema.md) §13) exists to record exactly that distinction.

**Item 7 deserves care.** IBKR borrow data reaches us through a brokerage relationship, and
ADR-0002 §13 keeps market-data and brokerage concerns separate. Using broker-supplied borrow
data for *research* is a different act from using it for a *pre-submission check*, and the
second is what Blueprint §12 actually requires. If only the second is permitted, that is still
a useful answer — it just is not a backtesting answer.

### 4.2 Step two: the free lead, then paid sources

| Step | Action | Cost |
|---|---|---|
| 2a | **Verify the S3 Partners AWS Data Exchange listing** — *"available free of charge"*, since 2015, *"All historical revisions"* (`PSR-BRW-023`, `PSR-BRW-024`). Genuinely free and broad, or a limited sample? | $0 |
| 2b | Orbisa premium via the IBKR Securities Lending Dashboard — 12 months, day resolution, UI-only (`PSR-IBK-039`, `PSR-IBK-038`) | $12.99 |
| 2c | ORTEX — resolve **credit economics** and **depth** before committing. Its multi-name endpoints are single-date snapshots (`PSR-BRW-008`), so a panel costs one call per trading day, and what a credit buys is undocumented | $149/mo API Quant tier |
| 2d | Institutional — S&P Global, EquiLend, FIS | `[Q]` |

**ORTEX is a candidate, not the assumed cheapest valid solution.** Revision 1 named it as the
cheapest valid option; it is neither established as valid (depth is `[U]` on every
ORTEX-controlled page, `PSR-BRW-049`) nor cheapest (steps 1 and 2a cost nothing). Note also
that ORTEX's advertised 16.6-year backtest is its **stock-scores** backtester, not its
securities-lending series (`PSR-BRW-016`) — reading it as borrow depth would be a material
error.

**Deliverables**
1. A written determination: what historical borrow data is obtainable, at what depth, breadth,
   granularity and price, under what licence.
2. If a source qualifies: schema 13 populated, `get_borrow_snapshot` implemented, freshness
   check 4.2.3 active, `coverage_scope` recorded per row.
3. If none qualifies: a recorded deferral, `BORROW_HISTORY_UNAVAILABLE` permanently asserted,
   and the short family left unbuilt.

**Tests (only if a source qualifies)**
- Borrow snapshots are source-keyed and never merged across sources.
- A run whose coverage is narrower than its backtest window carries `BORROW_COVERAGE_PARTIAL`.
- A short position in a run limited by `BORROW_HISTORY_UNAVAILABLE` is refused at manifest
  emission.
- Borrow data older than the freshness bound blocks rather than degrades.

**Acceptance:** §6 criterion 11 — a gate, not a checkbox.

**The rule that survives either outcome:** short backtesting stays **forbidden** until this
stage passes. Blueprint §24 keeps long+short as the locked target; this plan does not change
that and proposes no ADR to. It refuses to simulate the short half on data that does not exist.

## 5. Stage 3D — LEAN integration, manifests, blocking gates

| | |
|---|---|
| **Approvals required first** | **A4** (production information-set profile) before any capital-informing backtest |
| **Vendor dependency** | none |
| **Cost** | $0 |

**Deliverables**
1. Gold → LEAN export: date-keyed **and profile-keyed** universe files; custom data with
   availability times.
2. LEAN universe selection reads the exported historical membership file. **The highest-risk
   integration point in Phase 3.**
3. Research manifest emission (`manifest_version: 2`) with the preconditions in
   [reproducibility-and-provenance.md](reproducibility-and-provenance.md) §4.
4. `BLOCKING` gating wired into the query layer, the backtest entry point and manifest emission.
5. A data-quality report per ingestion run, including **checks not run and why**.
6. `scripts/phase3_preflight.py`, in the shape of the Phase-1 and Phase-2 preflights: static
   checks, non-zero exit, run before anything else.

**Tests**
- A LEAN backtest reads from the PIT layer, never from a broker feed.
- IBKR data never reaches the research store.
- A backtest refuses to start with a `BLOCKING` issue open.
- A manifest is refused on a dirty working tree, a missing profile, or mixed profiles.
- Same manifest, rerun → identical `run_id` and identical result hash.
- Two runs differing only in profile produce **different** `run_id`s.

**Acceptance:** §6 criteria 13, 14, 17, plus the adversarial fixtures.

---

## 6. Phase 3 acceptance criteria

| # | Criterion | Method |
|---|---|---|
| 1 | **Historical ticker / delisting test** | Resolve a known ticker reassignment at dates before and after the change; both resolve to the correct, different `security_id`. |
| 2 | **Survivorship-bias test** | A universe snapshot for a date ≥8 years past contains securities delisted since, at a rate consistent with the era. Zero delisted members **fails**. |
| 3 | **Split / dividend adjustment test** | Adjusted series recomputed from raw + admissible actions matches an independent reference within tolerance, **and** differs from a today-adjusted series at dates before the split. |
| 4 | **Filing-publication timing test** | A filing is inadmissible one second before its acceptance time and admissible one second after. |
| 5 | **Restatement / revision test** | With `AS_KNOWN_AT_AS_OF`: the original before the restating filing, the restatement after. With `ORIGINAL_FILING_ONLY`: the original in both cases. |
| 6 | **Analyst-estimate as-of test** | With the gap open, any attempt to serve estimates raises rather than returning current values. If a source is later licensed, a snapshot query returns the consensus that stood at `as_of`. |
| 7 | **Earnings-event timing test** | An after-market announcement is not admissible during the session that preceded it. |
| 8 | **Historical universe reconstruction test** | Rebuilding from the same inputs, rule version and profile is bit-identical. |
| 9 | **Stale-data rejection test** | A dataset past its freshness bound blocks live-facing queries. |
| 10 | **Deterministic dataset build** | Two builds from the same bronze artifacts produce identical `content_hash`. |
| 11 | **Borrow qualification test** | Either a qualified source passes §4, **or** the deferral is recorded and short research remains unauthorized. **No other route authorizes short research.** |
| 12 | **LEAN reads the PIT layer** | Universe, prices and fundamentals come from gold exports; no broker data path is reachable from research. |
| 13 | **No current data in an earlier as-of query** | See fixtures below. |
| 14 | **Reproducibility test** | A manifest reruns to an identical result hash, or fails loudly naming the missing input. |
| 15 | **Profile separation test** | The same query under three profiles yields three results ordered by admissibility, with three distinct `run_id`s — evaluated over records eligible under all three. |
| 16 | **Revision-view separation test** | `AS_KNOWN_AT_AS_OF` and `ORIGINAL_FILING_ONLY` differ on a known restatement; `LATEST_RESTATED` is unreachable from research. |
| 17 | **Adjustment-key test** | An adjusted artifact reproduces from its key; a tampered artifact is refused. |
| 18 | **Origin-eligibility test** | A `PROVIDER_DERIVED` record is refused under `PUBLIC_PIT`, served under the other two, and its exclusion is counted in the manifest. A `SYSTEM_OBSERVED` record is served only under `FORWARD_SYSTEM`. **Neither is rejected outright** — N7, N8 and N10 must pass. |
| 19 | **Provider-gap resolution test** | `EXCLUDE`, `BOUND` and `DOWNGRADE` each produce the documented behaviour and the documented token; no path serves a row under `PROVIDER_REALISTIC_PIT` on public timing. |

### 6.1 Adversarial fixtures — must FAIL the pipeline

Each is constructed to *produce* look-ahead if the guarantee is broken. A test suite that only
proves the happy path is how ADR-0004 §20 shipped a sign bug behind 100% green tests — the
fixture defaulted to a direction the broker never sends.

| # | Fixture | Must be rejected by |
|---|---|---|
| F1 | A fundamental row with `public_available_time` one day **before** its filing acceptance time | 4.1.5 |
| F2 | A restatement whose `public_available_time` precedes the revision it supersedes | 4.1.8 |
| F3 | A universe snapshot built from a current listing query | 6.3 / 6.4 |
| F4 | A price series adjusted with a split announced **after** `as_of` | 4.5.3 — and the correct path must produce a numerically different series |
| F5 | An earnings event stamped 09:00 ET when the release was 16:05 ET | 4.1.5, and it must measurably change the PEAD window |
| F6 | An estimate snapshot series with non-monotonic `snapshot_time` | 4.1.10 |
| F7 | A borrow snapshot copied forward from a later date | 4.2.3 |
| F8 | A ticker mapped to two securities on one date | 6.1 |
| F9 | A bar whose session date was truncated from a 20:00 ET UTC timestamp | 4.1.12 |
| F10 | A query with `as_of` omitted | fails to compile or raises — never defaults |
| F11 | A DST fall-back ambiguous instant stored unresolved | 4.1.11 |
| F12 | A short position in a run limited by `BORROW_HISTORY_UNAVAILABLE` | manifest emission |
| F13 | A backfilled row admitted at a date before `provider_available_time` under `PROVIDER_REALISTIC_PIT` | 4.3.5 |
| F14 | Two datasets resolved under different profiles in one result | 4.3.1 |
| F15 | `LATEST_RESTATED` reached from a backtest path | 4.4.1 + static test |
| F16 | A `BOUND` provider gap with no `PROVIDER_AVAILABILITY_UNKNOWN`, or a `DOWNGRADE` with no `PROFILE_DOWNGRADED_TO_PUBLIC` | 4.3.4 |
| F17 | An adjusted artifact whose bytes were altered after materialisation | 4.5.1 |
| F18 | A row we recorded as first seen before it was public | 4.1.1 |
| F19 | A `PROVIDER_DERIVED` consensus snapshot served in a `PUBLIC_PIT` result | 4.3.5 |
| F20 | A `SYSTEM_OBSERVED` borrow row served in a `PROVIDER_REALISTIC_PIT` result | 4.3.5 |
| F21 | `BOUND` applied to a `SYSTEM_OBSERVED` row, inventing a provider time | 4.3.10 |
| F22 | A row served under `PROVIDER_REALISTIC_PIT` whose governing time came from `public_available_time` — the withdrawn `DECLARE` | 4.3.3 |
| F23 | An `AUTHORITATIVE_PUBLIC` row with a null public time relabelled `PROVIDER_DERIVED` to get past the check | 4.0.3 |

### 6.2 Negative-control fixtures — must PASS

**New in revision 2, and the reason it exists is that revision 1's blanket temporal rule would
have failed all of these.** A check that over-blocks is not "safe"; it is a check that will be
loosened under deadline pressure by someone who no longer remembers why it was there.

| # | Fixture | Must be **accepted** |
|---|---|---|
| N1 | A scheduled earnings date announced 6 weeks before the event | `ANNOUNCED_FORWARD`; `effective_date` far after availability is correct |
| N2 | A split announced 1 May with a 10 June ex-date, queried on 2 May | knowable on 2 May; the **adjustment** must still not apply to bars before 10 June |
| N3 | An exchange holiday calendar published a year ahead | `ANNOUNCED_FORWARD` |
| N4 | A classification change announced ahead of its effective date | `ANNOUNCED_FORWARD` |
| N5 | A legitimate vendor backfill queried under `PUBLIC_PIT` with proven public timing | admissible historically |
| N6 | A record arriving 3 days late, within its latency budget | `INFO`/`WARNING` at most — never `BLOCKING` in research |
| **N7** | A `PROVIDER_DERIVED` consensus snapshot with a **null** `public_available_time`, queried under `PROVIDER_REALISTIC_PIT` | **admissible** — this is the exact row revision 2 would have rejected, and rejecting it is the bug |
| **N8** | The same row under `FORWARD_SYSTEM` | **admissible**, governed by `system_first_seen_time` |
| **N9** | The ordering invariant evaluated for a record eligible under only two of three profiles | **not asserted across the ineligible profile**, and not reported as a violation |
| **N10** | A `SYSTEM_OBSERVED` borrow row under `FORWARD_SYSTEM` | **admissible** — it is the only profile that can describe it, and forward validation is exactly what it is for |

---

## 7. Sequence and dependencies

```
A1 ──▶ 3A ──────▶ 3B ──────▶ 3D ──▶ A7 (accept Phase 3)
   A2─┘ A3─┘   A5─┘       A4─┘
                    ▲
        3C ─────────┘   (A6: fund, or defer)
        gate: short research
```

`A2` (licensing) precedes `A3` (purchase). `A4` (production profile) gates any backtest that
informs capital, and cannot be settled before a provider is chosen. 3C is off the critical path
by design: if borrow data is unaffordable or unfit, Phase 3 still completes — as a long-only
foundation with a recorded gap, which is a truthful outcome. It does not complete as a system
claiming short support.

## 8. Estimated effort

Blueprint §21 budgets 1–2 weeks for data feasibility and 2–3 for the data+factor foundation.
This plan covers the data half only.

| Stage | Estimate | Note |
|---|---|---|
| 3A | 2–3.5 weeks | universe construction, the five provider tests, and adjustment keying dominate |
| 3B | 1.5–2.5 weeks | EDGAR ingestion plus the restatement qualification; estimates are blocked, not built |
| 3C | 3–7 days | qualification research, not implementation |
| 3D | 1–1.5 weeks | LEAN export, profile plumbing, gating |

**Planning estimate, not a commitment.** Revision 2's estimates are higher than revision 1's
because the provider tests are real work that revision 1 had assumed away.

## 9. Top risks

1. **Vendor PIT semantics do not hold up under test.** The low-cost recommendation rests on
   the datasheet claim that data is time-indexed to the filing date with restatements
   separable. P1–P6 test it first. If P6 fails, `AS_KNOWN_AT_AS_OF` is a declared approximation
   rather than a guarantee — which is survivable, but only if it is declared.
2. **The estimates gap does not close.** Accepted and planned for. The cost is a degraded
   Blueprint §6 composite, declared rather than hidden.
3. **Borrow data stays unaffordable or unfit.** Accepted. V1 goes long-only with the short
   family recorded as unbuilt for lack of qualified data.
4. **Single-sourcing hides an error neither we nor the vendor sees.** Mitigated by declaring
   it (`SINGLE_SOURCE_UNVERIFIED`) rather than implying verification. Scenario B or C buys it
   down at a stated price.
5. **Silent look-ahead survives the checks.** The residual risk that matters. Mitigation is the
   adversarial fixtures **plus the negative controls** — an over-blocking check gets disabled,
   and a disabled check protects nothing — plus a standing rule: **a result that improves
   unexpectedly is investigated before it is believed.**
6. **Licence scope changes under the system.** Personal-use terms fit a personal research
   project and may not fit what this becomes. Gate G3 before purchase, and again before
   micro-live.

## 10. Explicitly not in this plan

> factor computation · strategy logic · ranking implementation · the portfolio and risk engine ·
> AI Research and Challenger agents · order generation · any change to Phase-1 or Phase-2
> execution code · brokerage interaction of any kind · production cloud infrastructure ·
> PostgreSQL deployment · dashboards · alerting · the kill switch

Phase 4 is not authorized, not scoped here, and not begun.
