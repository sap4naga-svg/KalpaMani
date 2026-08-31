# Phase 3 — Implementation Plan

## STATUS: **PROPOSED — NOT STARTED, NOT AUTHORIZED**

This is a plan to be executed later, if approved. **No stage below has begun.** No
infrastructure has been created, no provider contacted, no credential requested.

> **Revision 6 (2026-08-27).** **Storage moves from laptop-authoritative to private-AWS
> cloud-first** ([ADR-0007](../decisions/ADR-0007-cloud-first-research-data-plane.md)). §1.2 and
> §1.3 are rewritten: the authoritative Bronze/Silver/Gold location becomes a private,
> deletion-first S3 bucket, provenance and permitted outputs move to a separate control bucket,
> and `.runtime/data/` becomes an optional development cache. **Nothing else changes** — the
> point-in-time semantics, hashes, manifests, profiles, information-set model, coverage
> contracts and evidence requirements are untouched, because identity is a content hash and a
> hash does not know where its bytes live. No AWS resource exists.
>
> **Revision 5 (2026-08-26).** Deliverables follow the further schema splits; eight adversarial
> fixtures and four negative controls cover envelope exclusivity, resolved bounds, per-dataset
> policies and coverage contracts; and a **documentation-consistency audit**
> (`scripts/phase3_docs_audit.py`) checks the plan against itself.
>
> **Revision 4 (2026-08-26).** Provider test **P9** establishes whether daily bars are
> officially disseminated, provider-aggregated or system-aggregated — which decides whether
> price data is eligible under `PUBLIC_PIT` at all. Deliverables follow the earnings and
> fundamentals splits, and six adversarial fixtures plus three negative controls cover derived
> artifacts, bounds, profile resolution and required inputs.
>
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
time, original schema version, hash, and the run's declared `acquisition_mode` —
`QUALIFICATION`, `BACKFILL` or `UPDATE`
([ADR-0013](../decisions/ADR-0013-introduce-acquisition-mode-and-retire-is-backfill.md)), stated
by whoever governs the retrieval and never inferred from what arrived. It is **append-only**.
A re-fetch returning different bytes is a *new* artifact, not a replacement — which is what
makes a vendor backfill visible instead of silent, and what lets the profile model
(§[contract 3.3](pit-data-contract.md)) decide what to do about it.

**Silver** is where vendor semantics stop. Tickers become `security_id`. Local timestamps
become UTC instants with exact-or-bound derivations named. Vendor revision conventions become
`revision_sequence` rows. Nothing above silver knows which vendor supplied anything, except
through the provenance envelope carried for audit.

### 1.2 Technology evaluation

| Option | Fit | Verdict |
|---|---|---|
| **Parquet** | columnar, compressed, partitioned, no server | **recommended** for silver and gold |
| **DuckDB** | reads Parquet natively — including over S3 — zero-install, single file, strong analytical SQL | **recommended** as the research query engine |
| **PostgreSQL** | ADR-0001 and Blueprint §17 name it as the system database; correct for concurrent transactional state | **retained for operational state; not required by Phase 3** |
| **Private object storage (AWS S3)** | durable, always-available, independent of any one workstation, and — critically — **deletable on demand and provably so** | **selected** as the authoritative location ([ADR-0007](../decisions/ADR-0007-cloud-first-research-data-plane.md)) |
| Local disk (`.runtime/data/`) | fast, free, and tied to one machine's uptime and one machine's disk | **development cache and staging only**; not the research authority |
| **LEAN-compatible export** | required for 3D | **yes** — an export step, not a storage layer |
| TimescaleDB | ADR-0001 lists as optional | not needed; the workload is analytical, not time-series ingest |

**Recommendation: Parquet + DuckDB, on private AWS object storage.**

The *engine* choice is unchanged from revision 5 and its reasoning still holds. Phase 3 is a
single-writer, read-heavy analytical workload; DuckDB needs no server, no port, no credentials
and no operational surface, and it reads Parquet in S3 directly. What changed in revision 6 is
only **where the Parquet lives**.

Three things forced that, and none of them is visible while the data is synthetic:

1. **Ingestion cannot depend on a laptop being awake.** Daily and backfill fetches are a
   background obligation, not an interactive task.
2. **A full-universe, multi-year, profile-keyed rebuild is a batch job**, and running it on the
   machine that also edits code and drives IB Gateway couples two things that should not be.
3. **`.runtime/` is the one part of this system with no version-controlled copy** — necessarily,
   since it must never be committed. A disk failure loses every ingested artifact and every
   manifest that names one.

**The decisive reason is licensing, not convenience.** The candidate provider's §10 requires
deleting every copy of the data, from *"all computer systems you own or operate"*, within 30
days of a termination that may arrive without notice
([packet §3.C](provider-licensing-decision-packet.md)). A dedicated, deletion-first bucket makes
that a procedure over known prefixes; data scattered across a working laptop makes it a search.
See [ADR-0007](../decisions/ADR-0007-cloud-first-research-data-plane.md) for why this means the
licensed bucket deliberately runs **without** versioning, Object Lock, replication or archival
lifecycle — conventional durability features that each defeat the deletion obligation.

**This is not a replacement for PostgreSQL and does not contradict ADR-0001**, which selects
PostgreSQL for *"features, signals, trades, audit state"* — operational, transactional,
concurrently-written state. DuckDB here is a query engine over immutable research files, a
different job, and object storage is where those files sit. If experience later shows the
research layer belongs in PostgreSQL, that is an ADR, not a quiet substitution.

### 1.3 Where it lives

**Authoritative — private AWS, two buckets.** The split is
[ADR-0007](../decisions/ADR-0007-cloud-first-research-data-plane.md) §3: anything from which
vendor rows could be recovered is *licensed*; only artifacts that provably cannot reproduce
them are *control*.

```
LICENSED-DATA BUCKET  -- vendor-terminable; deleted on licence termination
s3://<licensed>/bronze/<provider>/<dataset>/<ingest_date>/<sha256>.json.gz
s3://<licensed>/silver/<entity>/<partition>/*.parquet
s3://<licensed>/gold/<dataset_version>/<entity>/*.parquet
s3://<licensed>/gold/<dataset_version>/adjusted/<artifact_id>.parquet
s3://<licensed>/qualification/<provider_test>/...

CONTROL / PERMITTED-OUTPUT BUCKET  -- survives termination
s3://<control>/manifests/<run_id>.json
s3://<control>/lineage/...
s3://<control>/receipts/...          missing-input receipts, deletion receipts
s3://<control>/outputs/...           approved non-reconstructable outputs
```

**The default is LICENSED.** An artifact nobody has classified is licensed until someone
classifies it. Over-classifying costs a deletion that was not required; under-classifying leaves
a copy in the one bucket the deletion procedure deliberately does not empty.

**The DuckDB catalog is derived, not authoritative.** It is rebuilt from the objects it indexes
and is treated as licensed wherever it materialises vendor rows.

**Local — `.runtime/data/`, and only ever these four roles:**

| Role | |
|---|---|
| optional development cache | a working copy, discardable at any time |
| temporary staging | before publication to the authoritative bucket |
| synthetic fixtures | repository-owned, fictitious, legible |
| local testing | including everything the A1 kernel does today |

Still git-ignored, and still the home for everything that must never be committed. **It is no
longer the production research authority.**

> **Cloud-first does not remove the laptop from the deletion obligation.** §10 reaches *"all
> computer systems you own or operate"*, so any local cache of licensed data is in scope and the
> [deletion runbook](../runbooks/vendor-data-cloud-deletion.md) covers it explicitly (step 13).
> Cloud-first narrows the surface; it does not eliminate it.

**Object identity does not move with the bytes.** A manifest names **content hashes**, never
bucket names or `s3://` URIs: a URI is a resolvable *location*, a hash is the *identity*. The
same artifact therefore has the same identity in the local cache, in the licensed bucket, and in
any future bucket or region, and renaming a bucket cannot invalidate a manifest. Everything the
point-in-time contract asserts about hashes, manifests, profiles, coverage and provenance is
unchanged by this relocation — see [ADR-0007](../decisions/ADR-0007-cloud-first-research-data-plane.md) §10.

**The AWS foundation is provisioned; nothing uses it.**
[`infra/aws/research-data-plane/`](../../infra/aws/research-data-plane/) was applied on 2026-08-27
— 36 resources verified against the live account, both research-data buckets empty
([status](../operations/aws-foundation-status.md)). Further AWS spending, provider credentials,
image builds and task execution each require their own separate written authorization.

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
1. `contracts/` — schemas 1, 1a, 2–7, 7a, 16, 17, 18 from [conceptual-schema.md](conceptual-schema.md).
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
| **P9** | **Bar construction and origin.** Are the daily bars officially disseminated (consolidated tape), aggregated by the provider from its own trade collection, or resampled by us? | decides `price_bar.information_origin`. If `PROVIDER_AGGREGATED`, **price data and everything derived from it — including the universe — are ineligible under `PUBLIC_PIT`**. Larger in consequence than the estimates gap, and revision 3 would never have surfaced it |

**What a bounded private empirical package could actually reach — the ceilings.**
[ADR-0018](../decisions/ADR-0018-bounded-private-empirical-sharadar-qualification.md) designs a
bounded owner-only package for P1–P9 and records the honest ceiling of each test. A ceiling is
what a run may **at most** report; a run may fall short of one and no run may exceed one. **The
ADR is accepted and approves architecture only** — PR #39 merged, and the merge authorized no
implementation, no infrastructure mutation and no execution: **no execution of that package is
authorized, so P1–P9 executions by it are ZERO.**

**A later, separate written authorization opened the implementation gate for one bounded
offline slice.** That slice exists as an **offline implementation candidate on an open pull
request** — synthetic fixtures and offline tests only, **not accepted and not in force until
that pull request merges**, and **never executed against AWS, a provider or a network**.
**Infrastructure design and mutation, Run A, Run B and the assessment run each remain NOT
AUTHORIZED**, and **P1–P9 executions by it are still ZERO**.

| | Ceiling under that package |
|---|---|
| P1 | `PARTIALLY_TESTED` after one run; **at most `TESTED` after a second, separated by calendar time**, and reachable **only through one combined assessment of Run A and Run B together**. The information-time resolution **stays bounded regardless of outcome**, because the vendor's update column is date-granular |
| P2 | **at most `PARTIALLY_TESTED`** — sampled delisted-history existence **is not proof of the population-wide survivorship claim** |
| P3 | the **schema question can reach `TESTED`**; announcement timing **remains approximated** where the field is absent |
| P4 | `DOCUMENTATION_RESOLVED` — classification history **cannot become empirically historized from a snapshot table** |
| P5 | **realistically at most `PARTIALLY_TESTED`** — split and dividend limbs may be tested; the **spinoff limb stays inconclusive while the provider's semantics are undocumented** |
| P6 | **`DEFERRED` to Stage 3B** |
| P7 | **`DEFERRED` to Stage 3B and EDGAR** |
| P8 | **`DEFERRED` to Stage 3B and EDGAR** |
| P9 | `DOCUMENTATION_RESOLVED` — price origin stays **`PROVIDER_DERIVED`** and **`PUBLIC_PIT` is not reachable from this evidence** |

**No aggregate verdict is produced by any of it.** Provider selection is **G1**, G1 is **OPEN**,
and it is an owner decision taken by a person reading evidence rather than a value returned by a
program.

**Two clarifications are EFFECTIVE — PR #42 merged.** Merge commit
`28239514b9e4e13f55ee98fa50877077e70bd593`, approved clarification head
`579259a62ff7561ae2991f3923ea8aa1d0064be8`; **while PR #42 was open they were proposed and
carried no authority**, and that stays true of those days. They change what the accepted
architecture *means*, not what it authorizes, and they authorize nothing:

- **The 1,800-second acquisition elapsed-time deadline.** It is **one actual elapsed-time
  deadline** measured on an **injected monotonic clock** over the complete acquisition execution
  phase — provider requests, pacing, local processing, Bronze publication, metadata resolution,
  locator construction, locator publication and permitted locator retry — rather than compile-time
  arithmetic over the provider-time component alone. It is a **safety bound on elapsed time and
  not a guarantee that 48 requests complete**: a slow provider halts the run short, publishes a
  `PARTIAL` locator, and the assessor refuses to evaluate it.
- **One combined assessment of Run A and Run B together**, after Run B. P1's `TESTED` ceiling is a
  cross-run question, so no per-run assessment can reach it. **Run A evidence alone caps P1 at
  `PARTIALLY_TESTED`**, and `TESTED` stays a ceiling rather than an expected outcome.

**The offline implementation candidate is unmerged and not accepted.** It has been
**corrected against the now-authoritative clarification** under a separately authorized
implementation correction, and it **awaits an independent re-review**; it is **not accepted
and not in force until its pull request merges**. **The merge approved clarification of
architecture only**, so
**implementation, infrastructure mutation, Run A, Run B and the combined assessment each remain
NOT AUTHORIZED**. **No execution of that package is authorized**, and **P1–P9 executions by it
are ZERO.**

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
1. Schemas 8, 9, 9a, 10, 10a–10e, 11, 12, 15, 15a.
2. EDGAR ingestion: `filing` records with **acceptance timestamps**, honouring SEC fair-access
   requirements (declared User-Agent, rate limiting).
3. `fundamental_fact` (**reported values only**) with all three revision views and
   `revision_chronology_completeness` populated from P6; `fundamental_derived_fact` as a
   `DERIVED_ARTIFACT` carrying lineage over the quarters it consumed.
4. The five earnings entities — `earnings_schedule`, `earnings_release`,
   `earnings_consensus_snapshot`, `earnings_surprise_artifact`, `guidance_event` — each with its
   own envelope, class and origin.
5. `get_fundamental_snapshot`, `get_fundamental_derived`, and the five earnings accessors.
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
7. `scripts/phase3_docs_audit.py` **already exists** and runs today — it is the only Phase-3
   artefact that does. It reads `docs/phase3/` and checks the plan against itself: enum values
   referenced by quality checks exist in the schema, source-only fields are not demanded of
   derived artifacts, exact and bound derivations map to the correct fields, every declared
   temporal semantics has its anchor, and no manifest rule names a retired field. It touches no
   runtime code and asserts nothing about data, because there is no data.

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
| 19 | **Provider-gap resolution test** | `EXCLUDE`, `BOUND` and `DOWNGRADE` each produce the documented behaviour and the documented token; no path serves a row under `PROVIDER_REALISTIC_PIT` on public timing; `BOUND` leaves the exact field null. |
| 20 | **Derived-artifact lineage test** | An artifact's availability equals the max over its lineage under each profile, plus `artifact_first_built_time` under `FORWARD_SYSTEM`; its eligibility is the input intersection; a rebuild from identical lineage is a no-op. |
| 21 | **Atomic-fact test** | No entity carries two origins, two classes or two envelopes on one row. The five earnings entities resolve independently and share only `event_id`. |
| 22 | **Profile-resolution test** | A downgraded run is labelled `PUBLIC_PIT` in its manifest, artifacts and `run_id`, carries `PROFILE_DOWNGRADED_TO_PUBLIC`, and is a different `run_id` from the same query resolved by `BOUND`. |
| 23 | **Required-input test** | A factor whose required domain fails its coverage contract refuses with `REQUIRED_INPUT_UNAVAILABLE`, naming scope, threshold and observed coverage; an optional domain proceeds with counts and a token. |
| 24 | **Envelope-exclusivity test** | A well-formed derived artifact passes every check without carrying a single source-envelope field; a well-formed source fact passes without lineage. Neither is graded by the other's rules. |
| 25 | **Exact-versus-bound test** | An approved bound satisfies a profile requirement and is reported as bounded; an approximation in an exact field is refused; `exact <= bound` holds. |
| 26 | **Per-dataset resolution test** | One run resolves two datasets by different policies; the canonical map is complete, its counts reconcile, and it changes `run_id`. |
| 27 | **Documentation-consistency audit** | `scripts/phase3_docs_audit.py` exits 0: every enum a check references exists in the schema, no source-only field is required of a derived artifact, exact and bound derivations name the correct fields, every declared temporal semantics has its anchor, and no manifest rule names a retired field. |

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
| F24 | A derived artifact served under a profile one of its inputs is ineligible for | 4.6.3 |
| F25 | A derived artifact whose recorded availability is earlier than its slowest input | 4.6.1 |
| F26 | A rebuild from identical lineage that moves `artifact_first_built_time` earlier | 4.6.4 |
| F27 | `system_first_seen_time` written into `provider_available_time` under `BOUND` | 4.0.10 |
| F28 | A downgraded run whose artifacts and `run_id` still name `PROVIDER_REALISTIC_PIT` | 4.3.11 |
| F29 | A factor computed under `PUBLIC_PIT` with its **required** estimates domain emptied by origin filtering | 4.7.1 — refuse `REQUIRED_INPUT_UNAVAILABLE` |
| F30 | A single row carrying both a scheduled date and a realised release timestamp | 4.0A.12 — the atomic-fact rule |
| F31 | A derived artifact rejected by a source-shaped origin check | must **not** happen — 4.0.0 admits `DERIVED_ARTIFACT`; see N14 |
| F32 | A `SYSTEM_OBSERVED` row carrying a `provider_available_upper_bound` | 4.0A.4 |
| F33 | A `DATE_PLUS_LAG` value written into `public_available_time` | 4.0A.7 |
| F34 | An exact public time later than its own `public_available_upper_bound` | 4.0A.8 |
| F35 | A bound relied upon whose derivation is not approved for its dataset | 4.0A.9 |
| F36 | A derived artifact declaring `temporal_fact_class = RETROSPECTIVE` | 4.0B.4 |
| F37 | A `SESSION_SCOPED` artifact with no `effective_session` | 4.0B.5 |
| F38 | A run whose `run_id` omits one dataset's gap policy from the hash | 4.3.13 |

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
| **N11** | A derived artifact whose inputs are all `AUTHORITATIVE_PUBLIC`, queried under `PUBLIC_PIT` | **admissible**, governed by the lineage max — deriving a value does not make it private |
| **N12** | A `PROVIDER_REALISTIC_PIT` row where `max(public, provider)` legitimately equals `public` because the provider offered it the instant it went public | **admissible** — 4.3.3 forbids *substitution*, not a genuine equality |
| **N13** | An **optional** enrichment domain emptied by origin filtering, declared optional, counted, token emitted | **admissible** — only *required* domains refuse |
| **N14** | A well-formed `DERIVED_ARTIFACT` with no `system_first_seen_time` and no source times | **admissible** — §4.0B applies, not §4.0A. Revision 4 would have raised three false BLOCKINGs here |
| **N15** | `AUTHORITATIVE_PUBLIC` with exact public null and an **approved** `DATE_PLUS_LAG` bound | **admissible** under `PUBLIC_PIT` — `resolved_public_time` resolves from the bound |
| **N16** | One run applying `BOUND` to one dataset and `EXCLUDE` to another | **admissible** — policies are per dataset |
| **N17** | A required domain at 97% coverage against a 95% `PER_SESSION` contract | **admissible** — the contract is met; only a breach refuses |

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
