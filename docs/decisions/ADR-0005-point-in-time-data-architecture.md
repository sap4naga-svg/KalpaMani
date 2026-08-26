# ADR-0005 — Point-in-Time Data Architecture and the Anti-Lookahead Contract

- **Status:** **Proposed** — planning under review. Not accepted, not implemented.
- **Date:** 2026-08-26
- **Deciders:** Project owner (human governance) — *pending*
- **Relates to:** ADR-0001 (System Foundation), ADR-0002 (BrokerAdapter and the Brokerage Boundary), ADR-0004 (Deterministic Order Identity, Idempotency, and Execution Lifecycle)
- **Authority:** Blueprint V2.1 §18 (Phase-0 point-in-time data feasibility), §17, §19, §26
- **Plan:** [`docs/phase3/`](../phase3/phase3-pit-data-foundation-charter.md)

---

## Context

Phases 1 and 2 built downward from the broker: connectivity, then a certified order
lifecycle. They deliberately contain no strategy and consume no research data, which is why
they could be certified at all — there was nothing for bad data to corrupt.

Phase 3 opens the other end of the system, and it carries a failure mode that is the mirror
image of Phase 2's. A duplicate order announces itself: the position is wrong, the broker
disagrees, reconciliation halts. **A look-ahead bug announces nothing.** It produces a better
backtest, and better results do not get investigated. By the time it surfaces, it has usually
been built on.

Blueprint §18 names the two hardest cases in advance — *"point-in-time analyst revisions and
realistic historical short borrow conditions — not ordinary OHLCV"* — and instructs: **"Do
not skip."** Phase-3 provider research (2026-08-26) confirms both, and finds that neither is
obtainable at individual cost. That finding, not the storage design, is what this ADR
principally exists to record.

Two constraints from earlier ADRs carry directly into this one:

- **ADR-0002 §13** — market-data code stays separate from brokerage execution, and broker
  data may never be the sole source for universe ranking or backtests.
- **ADR-0003 §4** — *"No safety claim may rest on a control the deployment path can silently
  reset."* Its generalisation applies here in a new form: **no correctness claim may rest on
  a vendor assertion that has not been tested.** "The vendor calls it point-in-time" is
  precisely the shape of assumption §25 of the Blueprint made about Read-Only API, and E-001
  records how that went.

---

## Decision

### 1. `source_available_time` is the single governing temporal field

Every record carries the instant at which KalpaMani could first have acted on it. It is
**derived**, never copied from a vendor publication field, through a fixed priority ladder
([pit-data-contract.md](../phase3/pit-data-contract.md) §4). Vendor-asserted publication time
is an *input* to that derivation and is never queried directly.

### 2. Every historical query takes a mandatory `as_of`

> **A research, scanning or backtest query returns only records whose
> `source_available_time` is at or before `as_of_time`.**

No default. No `latest` convenience. No overload without it. Enforced by static test, in the
manner ADR-0004 §10 already uses for the execution boundary — *"Enforced by test, not
convention."*

Historical and live access are **separate packages** (`data.pit`, `data.live`), not one
package with a flag. A flag can be set wrongly; a forbidden import fails in CI.

### 3. The store is bitemporal and append-only

Valid time (when the fact was true) and decision time (when we could have known it) are
independent axes and are never collapsed. A restatement, correction or vendor revision is a
**new row** with a higher `revision_sequence` and its own availability time. **Nothing is ever
updated in place.**

Research defaults to **as-originally-reported**. Restated values are reachable only by asking
for them explicitly — a factor computed on restated financials is a factor computed on the
future.

### 4. Unknown availability is not point-in-time

Where availability cannot be established, the record is excluded, or admitted only under an
**explicitly documented, version-controlled conservative lag** that is recorded in every
result that depended on it. `availability_derivation = UNKNOWN` may never participate in a
point-in-time query.

This is ADR-0004 §4a's reasoning applied to data instead of orders: an ambiguous state is
resolved conservatively and visibly, never optimistically and silently.

### 5. Historical universe membership is stored, never recomputed

Membership is materialised per session, per `universe_definition_version`, together with the
evaluation inputs that produced each decision. It is never derived by filtering a current
listing set, and every eligibility input must itself be admissible at that date.

This is the primary structural control against survivorship bias, and it is the one place
current data would be easiest to reach for.

### 6. Three layers, with an immutable base

```
BRONZE  immutable, content-addressed vendor payloads   -- append-only
SILVER  internal identities, UTC, explicit revisions   -- provenance retained
GOLD    versioned point-in-time research tables        -- materialised, hashed
```

Gold is **materialised and versioned**, not computed on demand, so a backtest input is an
artifact with a hash rather than the result of a query that may behave differently next week.

### 7. Parquet + DuckDB for research; PostgreSQL remains the operational database

**Proposed:** Parquet files under the git-ignored runtime area, queried by DuckDB, as the
research analytics layer for the current single-node Windows/Docker environment. No server,
no port, no credentials, no container.

**This does not supersede ADR-0001.** PostgreSQL remains the system of record for
operational, transactional, concurrently-written state — features, signals, trades, audit
state. DuckDB is a query engine over immutable research files, which is a different job.
Should the research layer later belong in PostgreSQL, that is a new ADR, not a quiet
substitution.

### 8. Vendor data is never committed, for licensing reasons as well as hygiene

Every low-cost provider evaluated forbids redistribution, and this repository is currently
**PUBLIC** (CLAUDE.md §3). Vendor payloads live only under `.runtime/`, with an explicit
ignore entry and a preflight check rather than reliance on an inherited one.

INC-0002 established the cost of getting this wrong: **a force-push does not delete anything
from GitHub.**

### 9. No brokerage identity enters the data platform

No brokerage account identifier, account-binding digest or broker-native order id appears in
any Phase-3 schema, artifact, manifest or quality report. The data platform has no reason to
know they exist, and the schema gives them nowhere to live (ADR-0002 §13, CLAUDE.md §3).

### 10. Blocking data quality refuses results rather than annotating them

A `BLOCKING` quality issue open against a dataset makes every dependent research, scanner and
backtest result **invalid and refused** — not returned with a warning, and not returned
empty. An empty result and a refusal are different answers.

Suppressing a quality issue is a **named human act** with a recorded reason. There is no bulk
suppression and no automatic ageing-out.

### 11. Reproducibility requires a manifest, not a commit SHA

> No result is reproducible merely because the Python code is version-controlled.

Every result carries a manifest naming the code commit, config version, dataset versions and
hashes, ingestion-run ids, `as_of` cutoff, universe/corporate-action/factor/lag-policy
versions, and random seed. `run_id` is **derived** from those inputs — the ADR-0004 §2
principle, applied to research: *"No `uuid4()`. No timestamps."*

A manifest is **refused** on a dirty working tree, on an open `BLOCKING` issue, or on an
unverifiable content hash. An unreproducible result that looks reproducible is the dangerous
one, because it gets cited later by someone who was not present.

### 12. Every manifest carries a mandatory `limitations` block

An empty list is a positive claim that nothing was approximated, not a default. Any report or
figure derived from a manifest reproduces its limitations. **A performance figure quoted
without its limitations is quoted wrongly.**

### 13. Point-in-time analyst revisions are unavailable at individual cost — declared, not approximated

Research on 2026-08-26 found no credible individually-priced source of historical analyst
revision *timing*. The genuine sources (I/B/E/S detail history, FactSet Estimates) are
institutional and quoted by sales. Retail-tier "analyst estimates" endpoints return **current**
estimates.

> **A current consensus value with no historical snapshot or revision timing is NOT
> ACCEPTABLE for point-in-time backtesting.** It is not a degraded version of the right data;
> it is the answer sheet.

**Decision.** The Blueprint §6 earnings/revision composite is built from its point-in-time
available sub-components — as-reported fundamental surprise, post-filing price and volume
response, margin and growth from filings. The **analyst revision sub-factor is marked
`ANALYST_REVISIONS_UNAVAILABLE`** in every manifest that touches the composite, and no
performance may be attributed to it.

**This ADR does not change the Blueprint §6 weights and does not propose to.** CLAUDE.md §2
forbids a lower authority silently redesigning the system. If the gap persists through Phase
3B and the weights must change, that is a separate ADR raised at the time, with evidence.
What is decided here is only that the gap will not be filled with a number that resembles the
real thing.

### 14. Historical borrow data is unavailable at individual cost — the short family is gated, not simulated

IBKR publishes **current** shortable availability and fees and does not archive them. Sources
with genuine history are institutional, or of unverified depth.

> **Current IBKR availability MUST NOT be represented as historical borrow availability.**

**Decision.** Phase 3C is a **qualification gate**. Until it passes:

- short backtests are **forbidden**, not discouraged;
- no document may describe short support as available;
- a run limited by `BORROW_HISTORY_UNAVAILABLE` that contains a short position is **refused at
  manifest emission** — the gate is mechanical, not editorial.

Deferral is an acceptable outcome. Blueprint §24 keeps direction locked as long **and** short;
this ADR changes nothing about that target and records only that the short half is **unbuilt
for lack of data**.

Blueprint §12 already required historical short backtests to be *"discounted unless borrow
cost and availability are modeled conservatively."* There is no conservative model of a value
that was never observed, so this ADR converts that caution into a gate. A lag can correct a
timing error; it cannot manufacture a missing observation.

### 15. LEAN consumes exported point-in-time artifacts, never broker data

LEAN universe selection reads a **date-keyed exported membership file**; it does not query a
live universe API and does not filter a current list. Fundamentals, estimates and events reach
LEAN as custom data carrying explicit availability times. IBKR data is never written into the
research store.

This is ADR-0002 §13 and Blueprint §26 restated at the integration point that would otherwise
be the easiest place to violate them.

---

## Consequences

**Positive**

- Look-ahead becomes something a query must *refuse*, rather than something a reviewer must
  notice.
- The bitemporal, append-only store makes silent history rewriting structurally impossible,
  in the same way ADR-0004 made duplicate entry structurally impossible rather than unlikely.
- The two hardest data problems are named, evidenced and gated at planning time rather than
  discovered mid-backtest — which is the outcome Blueprint §18 was written to force.
- The long-side foundation is affordable: roughly **$29–$60/month**.
- Parquet keeps the migration to PostgreSQL or object storage a loader change.

**Negative / accepted**

- **A locked Blueprint factor is degraded.** The revision sub-factor is unavailable, and no
  amount of engineering substitutes for data that must be bought.
- **Half the locked direction is unbuilt.** Long-only V1 until borrow history is funded.
- Materialised, versioned gold costs disk and rebuild time. Accepted: the alternative is
  results that cannot be reproduced.
- Fail-closed on unknown availability means the system will sometimes refuse data a human
  would have judged safe. Same trade as ADR-0004: a refusal is recoverable, a contaminated
  research programme is not.
- Cross-provider reconciliation doubles ingestion work for several domains. Accepted — one
  unverified vendor claim is exactly what ADR-0003 §4 warns against.

**Neutral**

- DuckDB adds a dependency and removes an operational surface. Net simplification for a
  single-node workload.

---

## Scope limits

This ADR authorises **nothing to be built**. It records the contract Phase 3 would implement
if authorised, and the constraints that would bind it.

It does **not** authorise: any provider purchase or trial; any credential; strategy or factor
implementation; the portfolio or risk engine; AI agents; any change to Phase-1 or Phase-2
execution code; any brokerage interaction; PostgreSQL deployment; or Phase 4.

`LIVE_TRADING_HARD_DISABLED` remains `True`. Both ADR-0001 gates remain closed.

---

## Verification

To be enforced by `tests/unit/test_phase3_pit_contract.py` and
`scripts/phase3_preflight.py` **when implementation is authorised** — none of this exists yet:

`as_of` mandatory with no default on every historical accessor · no `latest`/`current` path in
research code · `data.pit` and `data.live` mutually exclusive by import · research modules
cannot import `execution` or `broker` · restatement invisible before its filing acceptance
time · as-reported is the default and restated requires an explicit request · historical
universe reconstruction deterministic and containing delisted securities · adjustment
recomputed from raw plus admissible actions · session dates sourced from the calendar, never
truncated from UTC · DST-ambiguous instants resolved · `BLOCKING` quality issue refuses
dependent results · manifest refused on a dirty tree · derived `run_id` reproducible ·
short position refused under `BORROW_HISTORY_UNAVAILABLE` · no brokerage identifier in any
schema · the twelve adversarial look-ahead fixtures.

---

## Follow-ups

Listed by topic. Numbers are taken when an ADR is written, from the next unused number in
`docs/decisions/`.

- **Analyst-estimate provider selection** — if a point-in-time source becomes affordable.
- **Blueprint §6 composite weights** — only if the estimates gap persists and the weights must
  change. Requires evidence, and its own ADR.
- **Borrow-history provider selection** — the Phase-3C outcome.
- **PostgreSQL-backed trade state store** — carried forward from ADR-0004.
- **Live-execution Gate 2 authorization mechanism** — before live trading is considered.
