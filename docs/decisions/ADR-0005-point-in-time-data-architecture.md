# ADR-0005 — Point-in-Time Data Architecture and the Anti-Lookahead Contract

- **Status:** **Proposed** — planning under review. Not accepted, not implemented.
- **Date:** 2026-08-26 (revision 2)
- **Deciders:** Project owner (human governance) — *pending*
- **Relates to:** ADR-0001 (System Foundation), ADR-0002 (BrokerAdapter and the Brokerage Boundary), ADR-0004 (Deterministic Order Identity, Idempotency, and Execution Lifecycle)
- **Authority:** Blueprint V2.1 §18 (Phase-0 point-in-time data feasibility), §17, §19, §26
- **Plan:** [`docs/phase3/`](../phase3/phase3-pit-data-foundation-charter.md)

---

## Revision history

| Rev | Date | Change |
|---|---|---|
| 1 | 2026-08-26 | First draft. |
| **2** | **2026-08-26** | Independent review of PR #6. Six substantive corrections: the single availability field is **split into four with explicit information-set profiles** (§2–§4); **revision views are made explicit** and the contradictory default resolved (§6); **adjusted prices resolved to one design** (§8); **temporal checks made class-aware** (§7); **cross-validation no longer assumed free** (§12); a **vendor-licensing gate** added before any purchase (§13). IBKR borrow history reclassified from *absent* to *unresolved* (§15). |

---

## Context

Phases 1 and 2 built downward from the broker: connectivity, then a certified order lifecycle.
They deliberately contain no strategy and consume no research data, which is why they could be
certified at all — there was nothing for bad data to corrupt.

Phase 3 opens the other end of the system, and it carries a failure mode that is the mirror
image of Phase 2's. A duplicate order announces itself: the position is wrong, the broker
disagrees, reconciliation halts. **A look-ahead bug announces nothing.** It produces a better
backtest, and better results do not get investigated. By the time it surfaces, it has usually
been built on.

Blueprint §18 names the two hardest cases in advance — *"point-in-time analyst revisions and
realistic historical short borrow conditions — not ordinary OHLCV"* — and instructs: **"Do not
skip."** Provider research (2026-08-26) confirms both, and finds neither obtainable at
individual cost. That finding, not the storage design, is what this ADR principally exists to
record.

Two constraints from earlier ADRs carry directly into this one:

- **ADR-0002 §13** — market-data code stays separate from brokerage execution, and broker data
  may never be the sole source for universe ranking or backtests.
- **ADR-0003 §4** — *"No safety claim may rest on a control the deployment path can silently
  reset."* Its generalisation applies here in a new form: **no correctness claim may rest on a
  vendor assertion that has not been tested.** "The vendor calls it point-in-time" is exactly
  the shape of assumption Blueprint §25 made about Read-Only API, and E-001 records how that
  went. Revision 2 of this ADR exists partly because revision 1 committed the same error twice
  — once about vendor revision chronology, once about what QuantConnect data costs.

---

## Decision

### 1. Availability is not one fact — it is four

**Superseded from revision 1**, which defined a single `source_available_time` and thereby
answered three different questions with one number. Every record carries:

| Field | Meaning |
|---|---|
| `public_available_time` | when the fact became publicly obtainable from the authoritative source |
| `provider_available_time` | when the selected provider first offered the record (nullable) |
| `system_first_seen_time` | when KalpaMani first held it |
| `ingestion_time` | when this particular row was written |

`public_available_time` is **derived**, never copied from a vendor field, through a fixed
priority ladder ([contract §5.1](../phase3/pit-data-contract.md)). A vendor's asserted
publication time is an *input* to that derivation, never the answer.

### 2. The governing time is computed per information-set profile, not stored

```
PUBLIC_PIT              = public_available_time
PROVIDER_REALISTIC_PIT  = max(public, provider)
FORWARD_SYSTEM          = max(public, provider, system_first_seen)
```

`decision_available_time` is **not a column**. Storing it would bake one profile into the data.
The three profiles are strictly ordered in conservatism, and that ordering is asserted as an
invariant rather than assumed.

**Every historical query names a profile. Every manifest records it. A single result may never
mix profiles** — mixing is refused at manifest emission, not annotated.

### 3. Backfill admissibility is a property of the profile

| Profile | A vendor backfill delivered today, describing 2015 |
|---|---|
| `PUBLIC_PIT` | admissible in a 2015 query **only if** authoritative public timing is proven |
| `PROVIDER_REALISTIC_PIT` | **not** admissible before the provider supplied it |
| `FORWARD_SYSTEM` | **not** admissible before we received it |

This is the case the split exists for. Under revision 1 all three readings were representable
by the same field and the code would have picked whichever the ingestion path happened to have.

### 4. Unknown provider availability is declared or excluded, never assumed

Under `PROVIDER_REALISTIC_PIT`, a null `provider_available_time` is resolved per dataset as
either **EXCLUDE** (the record does not participate) or **DECLARE** (it participates on
`public_available_time`, and the run carries `PROVIDER_AVAILABILITY_UNKNOWN`). There is no
third option and no silent fallback.

### 5. Unknown public availability is not point-in-time under any profile

Excluded, or admitted only under an **explicitly documented, version-controlled conservative
lag** recorded in every result that depended on it. A lag applies to `public_available_time`
only; **it may never invent a `provider_available_time`.**

This is ADR-0004 §4a's reasoning applied to data instead of orders: an ambiguous state is
resolved conservatively and visibly, never optimistically and silently.

### 6. Revision views are explicit, and there is no implicit default

**Superseded from revision 1**, which stated two contradictory defaults — "as originally
reported" in one document and "highest admissible revision" in another.

| View | Returns | Available to research |
|---|---|---|
| `AS_KNOWN_AT_AS_OF` | latest revision whose `decision_available_time <= as_of` | **default** |
| `ORIGINAL_FILING_ONLY` | `revision_sequence = 0` only, if admissible | yes, explicitly |
| `LATEST_RESTATED` | newest revision, ignoring `as_of` | **forbidden** |

`AS_KNOWN_AT_AS_OF` is correct as the default because it is what a decision-maker at that
moment actually had — including any restatement already published. `LATEST_RESTATED` is not
point-in-time, is unreachable from research and backtest code by static test, and any result
using it carries `NON_PIT_RESTATED_VIEW` and **may not be called a backtest**.

`revision_view` is required, positional, and has no default value — the same discipline
`as_of` gets, and for the same reason.

**Vendor revision chronology must be proven.** A provider's "as reported" versus "most recent
reported" dimensions establish that two endpoints differ; they do **not** establish that every
intermediate revision survives with its own timestamp. `AS_KNOWN_AT_AS_OF` needs the full
chronology. Where only endpoints exist, the view degrades to a two-point approximation and the
run carries `REVISION_CHRONOLOGY_INCOMPLETE`. **Known-restatement qualification is a BLOCKING
provider test in Phase 3A/3B.** Revision 1 asserted the capability; revision 2 tests for it.

### 7. Temporal invariants are fact-class-aware

**Superseded from revision 1**, whose blanket rule "availability before observation is
BLOCKING" would have blocked every correctly-recorded scheduled earnings date, announced split
and future exchange holiday.

| Class | Invariant | Examples |
|---|---|---|
| `RETROSPECTIVE` | `public_available_time >= observation_time` | bars, filings, realised releases |
| `ANNOUNCED_FORWARD` | `public_available_time >= announcement_time`; **no constraint between `effective_date` and availability** | scheduled earnings, announced splits, calendars, index changes |
| `SAMPLED_STATE` | `public_available_time >= sample_time` | borrow, classification, shares outstanding |

Every entity declares a class; there is no default. Knowing a split is coming and applying its
adjustment are two different operations, and **only the second is look-ahead**.

Separately, and expressed as exact inequalities in
[data-quality-plan.md](../phase3/data-quality-plan.md) §4:

- `system_first_seen_time < public_available_time` → **BLOCKING** (impossible; a timestamp is
  wrong)
- `system_first_seen_time − public_available_time > latency_budget` → **WARNING** (late
  arrival), escalating to **BLOCKING** only where a live freshness bound is breached

Revision 1 collapsed these two into one check. They are different failures with different
severities.

### 8. Adjusted prices: computed, with materialisation only as a keyed cache

**Resolves a direct contradiction in revision 1**, where the schema said adjusted bars are
never stored and the implementation plan listed them as gold contents.

> **Design A is normative.** An adjusted series is *defined* as a pure function of raw bars,
> the corporate actions admissible at `as_of` under the profile, and an adjustment policy. It
> is computed at query time. **No adjusted series is a stored fact.**

> **Materialisation is permitted only as an immutable, verifiable cache artifact** keyed by
> `adjustment_policy`, `information_set_profile`, `as_of_epoch`,
> `corporate_action_dataset_version`, `raw_bar_dataset_version`, `security_id_scope` and
> `content_hash`. It must reproduce bit-identically from its key; a mismatch is **BLOCKING**,
> not a cache miss. No unkeyed adjusted table exists anywhere in the system.

The ceremony is warranted because "the adjusted close of a stock on a past date" is not a
number — it is a number *per information set*. Storing one without its key is how a research
programme ends up with two truths and no way to tell which it used.

### 9. Historical universe membership is stored, never recomputed, and is profile-keyed

Materialised per session, per `universe_definition_version`, **per profile**, together with the
evaluation inputs that produced each decision. Never derived by filtering a current listing
set; every eligibility input must itself be admissible at that date under that profile.

This is the primary structural control against survivorship bias, and the one place current
data would be easiest to reach for.

### 10. Three layers, with an immutable base

```
BRONZE  immutable, content-addressed vendor payloads   append-only
SILVER  internal identities, UTC, explicit revisions   provenance retained
GOLD    versioned PIT research artifacts              materialised, hashed, profile-keyed
```

Gold is materialised and versioned rather than computed on demand, so a backtest input is an
artifact with a hash rather than the result of a query that may behave differently next week.

### 11. Parquet + DuckDB for research; PostgreSQL remains the operational database

**Proposed:** Parquet files under the git-ignored runtime area, queried by DuckDB, as the
research analytics layer for the current single-node Windows/Docker environment. No server, no
port, no credentials, no container.

**This does not supersede ADR-0001.** PostgreSQL remains the system of record for operational,
transactional, concurrently-written state — features, signals, trades, audit state. DuckDB is
a query engine over immutable research files, a different job. Should the research layer later
belong in PostgreSQL, that is a new ADR, not a quiet substitution.

### 12. Cross-validation is a licensed capability, not a free one

**Superseded from revision 1**, which described a full local QuantConnect cross-check as
"bundled" and therefore free. Review found that current official pricing treats the local
Security Master and local US equity history as **paid products**, distinct from free cloud
access.

Decision:

1. **No cross-check is assumed free.** Every cross-validating source is costed explicitly, and
   [provider-evaluation.md](../phase3/provider-evaluation.md) enumerates at least three
   scenarios: single-source, plus paid security master, plus paid price history.
2. **Cloud-only or sampled access is recorded as such** and may not be described as a
   broad-universe local cross-check.
3. **Where only one source is licensed for a domain, the affected cross-provider checks do not
   run**, and every dependent result carries `SINGLE_SOURCE_UNVERIFIED`. A check that cannot
   run is declared, never quietly skipped.

Single-sourcing is an acceptable engineering choice. Single-sourcing while implying
verification is not, and revision 1's cost table implied it.

### 13. Vendor licensing is a gate that precedes purchase

**New in revision 2.** The low-cost individual licences examined are personal-use-only and
restrict publication of analysis derived from the data.

Before any purchase or credential (authorization **A2**, which precedes A3), written
clarification must be obtained covering:

1. personal automated trading of the owner's own funds;
2. future entity, professional, or micro-live use;
3. **publication of empirical vendor-quality evaluations in a public repository**;
4. retention and deletion obligations after termination.

Until clarified: **do not purchase, do not credential, do not publish empirical conclusions
derived from subscribed data, and keep vendor payloads out of Git.** Planning comparisons drawn
from public documents remain permitted, with sources cited.

The sequencing is deliberate. Buying first and reading the terms afterwards is how a public
repository acquires a licence breach it cannot recall — the same mechanism, in a different
domain, that left INC-0002 open. **A force-push does not delete anything from GitHub.**

### 14. Vendor data is never committed

Every low-cost provider evaluated forbids redistribution, and this repository is currently
**PUBLIC** (CLAUDE.md §3). Vendor payloads, derived quality reports and research manifests
built from subscribed data live only under `.runtime/`, with an explicit ignore entry and a
preflight check rather than reliance on an inherited one.

### 15. Historical borrow: unresolved, not absent — and the short family is gated either way

**Superseded from revision 1**, which claimed categorically that "IBKR does not archive
historical borrow data". That was wrong, and wrong in a way that mattered: it generalised one
secondary report about the FTP feed to everything IBKR offers.

IBKR documents **four** historical borrow surfaces, and one of them is programmatic through
the TWS API this system already connects to: `reqHistoricalData` with `whatToShow=FEE_RATE`
returns OHLC bars of the stock borrow fee rate, *"available in various units of duration up to
the present moment"* (`PSR-IBK-010`, `PSR-IBK-034`). **Its historical depth is documented
nowhere** (`PSR-IBK-043`), and that single unknown decides whether the short family is blocked
by data or merely by effort.

**Phase 3C must first qualify what IBKR already provides** against an explicit nine-item
checklist — `FEE_RATE` depth, fields, per-symbol versus bulk, granularity, delisted-name
survival, revision behaviour, licensing (**no public IBKR page states a permitted use**,
`PSR-IBK-044`), bucketing, and whether it can support broad-universe historical short research
([implementation-plan.md](../phase3/implementation-plan.md) §4.1). Only then does the question
move outward — first to a **free** lead (an S3 Partners AWS Data Exchange listing stating
*"available free of charge"* with coverage since 2015, `PSR-BRW-023`), then to paid sources,
where **ORTEX is a candidate, not the assumed cheapest valid solution.**

Establishing `FEE_RATE` depth requires calling the broker. **That is broker interaction and it
is authorization A6, not planning.** This ADR records the question; it does not answer it.

The gate itself is unchanged and unconditional:

> **Short backtests are forbidden — not discouraged — until a source qualifies.** No document
> may describe short support as available. A run limited by `BORROW_HISTORY_UNAVAILABLE`
> containing a short position is **refused at manifest emission**.

Deferral is an acceptable outcome. Blueprint §24 keeps direction locked as long **and** short;
this ADR changes nothing about that target and records only that the short half is **unbuilt
for lack of qualified data**. Blueprint §12 already required historical short backtests to be
*"discounted unless borrow cost and availability are modeled conservatively"*; there is no
conservative model of a value that was never observed, so the caution becomes a gate. A lag can
correct a timing error; it cannot manufacture a missing observation.

### 16. Point-in-time analyst revisions are unavailable at individual cost — declared, not approximated

No credible individually-priced source of historical analyst revision *timing* was identified.
The genuine sources are institutional and quoted by sales. Retail-tier "analyst estimates"
endpoints return **current** estimates.

> **A current consensus value with no historical snapshot or revision timing is NOT ACCEPTABLE
> for point-in-time backtesting.** It is not a degraded version of the right data; it is the
> answer sheet.

**Decision.** The Blueprint §6 earnings/revision composite is built from its point-in-time
available sub-components — as-reported fundamental surprise, post-filing price and volume
response, margin and growth from filings. The **analyst revision sub-factor is marked
`ANALYST_REVISIONS_UNAVAILABLE`** in every manifest that touches the composite, and no
performance may be attributed to it.

**This ADR does not change the Blueprint §6 weights and does not propose to.** CLAUDE.md §2
forbids a lower authority silently redesigning the system. If the gap persists through Phase 3B
and the weights must change, that is a separate ADR raised at the time, with evidence. What is
decided here is only that the gap will not be filled with a number that resembles the real
thing.

### 17. Blocking data quality refuses results rather than annotating them

A `BLOCKING` quality issue open against a dataset makes every dependent research, scanner and
backtest result **invalid and refused** — not returned with a warning, and not returned empty.
An empty result and a refusal are different answers.

Suppressing a quality issue is a **named human act** with a recorded reason. No bulk
suppression, no automatic ageing-out.

### 18. Reproducibility requires a manifest, not a commit SHA

> No result is reproducible merely because the Python code is version-controlled.

Every result carries a manifest naming the code commit, config version, dataset versions and
hashes, ingestion-run ids, `as_of` cutoff, **information-set profile**, **revision view**,
adjustment policy and artifacts, universe/corporate-action/factor/lag-policy versions, and
random seed. `run_id` is **derived** from those inputs — ADR-0004 §2 applied to research: *"No
`uuid4()`. No timestamps."*

A manifest is **refused** on a dirty working tree, an open `BLOCKING` issue, a missing profile
or revision view, mixed profiles, an unverifiable content hash, or an undeclared provider gap.

### 19. Every manifest carries a mandatory `limitations` block

An empty list is a positive claim that nothing was approximated, not a default. Any report or
figure derived from a manifest reproduces its limitations. **A performance figure quoted
without its limitations is quoted wrongly.**

### 20. LEAN consumes exported point-in-time artifacts, never broker data

LEAN universe selection reads a **date-keyed, profile-keyed exported membership file**; it does
not query a live universe API and does not filter a current list. Fundamentals, estimates and
events reach LEAN as custom data carrying explicit availability times. IBKR data is never
written into the research store.

This is ADR-0002 §13 and Blueprint §26 restated at the integration point that would otherwise
be the easiest place to violate them.

### 21. No brokerage identity enters the data platform

No brokerage account identifier, account-binding digest or broker-native order id appears in
any Phase-3 schema, artifact, manifest or quality report. The data platform has no reason to
know they exist, and the schema gives them nowhere to live (ADR-0002 §13, CLAUDE.md §3).

---

## Open decision gates

This ADR is **Proposed**. The following are deliberately **not decided** here, and each
requires a separate written human decision before the work it gates begins:

| # | Gate | Blocks | Authorization |
|---|---|---|---|
| G1 | **Provider selection** — which vendors, for which domains | any ingestion implementation | A3 |
| G2 | **Information-set profile for production research** — which of the three governs results that inform capital | any backtest used to justify deployment | A4 |
| G3 | **Vendor licensing** — written clarification on personal/professional scope, publication of derived evaluations, and retention | **any purchase or credential** | A2 |
| G4 | **The analyst-estimate gap** — accept the degraded composite, or fund an estimates licence | building the earnings/revision composite | A5 |
| G5 | **Borrow-history qualification** — qualify IBKR's own history, then a paid source, or formally defer the short family | any short-side research | A6 |

G2 is genuinely open, not a formality. `provider_available_time` is only obtainable for a
provider already chosen, so G2 cannot be settled before G1 — and until it is, no result may
describe itself as realistic rather than merely public.

---

## Consequences

**Positive**

- Look-ahead becomes something a query must *refuse*, rather than something a reviewer must
  notice.
- Separating the information times makes a whole class of question answerable that revision 1
  could not even express — in particular whether a result reflects what the market knew, what a
  subscriber knew, or what we actually held.
- The three-axis, append-only store makes silent history rewriting structurally impossible, as
  ADR-0004 made duplicate entry structurally impossible rather than unlikely.
- The two hardest data problems are named, evidenced and gated at planning time rather than
  discovered mid-backtest — the outcome Blueprint §18 was written to force.
- Parquet keeps migration to PostgreSQL or object storage a loader change.

**Negative / accepted**

- **A locked Blueprint factor is degraded.** The revision sub-factor is unavailable, and no
  amount of engineering substitutes for data that must be bought.
- **Half the locked direction is unbuilt.** Long-only V1 until borrow history qualifies.
- **Cross-validation costs money.** Revision 1 assumed otherwise; single-sourcing is now an
  explicit, declared choice with a limitation token attached.
- Three profiles and three revision views mean more parameters on every query and more
  combinations to test. Accepted: the alternative is one parameter that silently means
  whichever thing the ingestion code had.
- Fail-closed on unknown availability means the system will sometimes refuse data a human
  would have judged safe. Same trade as ADR-0004: a refusal is recoverable, a contaminated
  research programme is not.

**Neutral**

- DuckDB adds a dependency and removes an operational surface. Net simplification for a
  single-node workload.

---

## Scope limits

This ADR authorises **nothing to be built**. It records the contract Phase 3 would implement if
authorised, and the constraints that would bind it.

It does **not** authorise: any provider purchase, trial or credential; strategy or factor
implementation; the portfolio or risk engine; AI agents; any change to Phase-1 or Phase-2
execution code; any brokerage interaction; PostgreSQL deployment; or Phase 4.

`LIVE_TRADING_HARD_DISABLED` remains `True`. Both ADR-0001 gates remain closed.

---

## Verification

To be enforced by `tests/unit/test_phase3_pit_contract.py` and `scripts/phase3_preflight.py`
**when implementation is authorised** — none of this exists yet:

`as_of`, `information_set_profile` and `revision_view` mandatory with no defaults on every
historical accessor · no `latest`/`current` path in research code · `LATEST_RESTATED`
unreachable from research · `data.pit` and `data.live` mutually exclusive by import · research
modules cannot import `execution` or `broker` · profile ordering invariant holds · mixed
profiles refused · backfill inadmissible under the profiles that forbid it · restatement
invisible before its filing acceptance time · `AS_KNOWN_AT_AS_OF` returns a published
restatement and `ORIGINAL_FILING_ONLY` does not · incomplete revision chronology forces its
limitation token · **`ANNOUNCED_FORWARD` facts with far-future effective dates are NOT
blocked** · leakage and late-arrival graded separately · adjusted artifacts reproduce from
their keys · unkeyed adjusted series refused · historical universe reconstruction deterministic,
profile-keyed, and containing delisted securities · session dates sourced from the calendar ·
DST-ambiguous instants resolved · `BLOCKING` quality issue refuses dependent results · manifest
refused on a dirty tree or a missing profile · derived `run_id` reproducible · short position
refused under `BORROW_HISTORY_UNAVAILABLE` · no brokerage identifier in any schema · the
adversarial look-ahead fixtures, **including the negative controls that must pass**.

---

## Follow-ups

Listed by topic. Numbers are taken when an ADR is written, from the next unused number in
`docs/decisions/`.

- **Analyst-estimate provider selection** — if a point-in-time source becomes affordable.
- **Blueprint §6 composite weights** — only if the estimates gap persists and the weights must
  change. Requires evidence, and its own ADR.
- **Borrow-history provider selection** — the Phase-3C outcome.
- **Production information-set profile** — gate G2, once a provider is chosen.
- **PostgreSQL-backed trade state store** — carried forward from ADR-0004.
- **Live-execution Gate 2 authorization mechanism** — before live trading is considered.
