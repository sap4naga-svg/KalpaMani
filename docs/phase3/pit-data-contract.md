# The KalpaMani Point-in-Time Data Contract

**Status: PROPOSED — planning only.** Normative wording ("must", "fails closed") describes
the contract being proposed, not behaviour that exists. Nothing here is implemented.

Governed by [ADR-0005](../decisions/ADR-0005-point-in-time-data-architecture.md).

> **Revision 2 (2026-08-26).** Independent review of PR #6 found that the first draft
> collapsed three different notions of "available" into one field, and stated two
> contradictory defaults for restated financials. Both are corrected here. The field
> `source_available_time` from revision 1 **no longer exists**; it is split into four
> (§2) and resolved by an explicit information-set profile (§3). Revision views are now
> explicit (§6).

---

## 1. The rules

> **R1.** Every research, scanning and backtest query returns only those records whose
> **`decision_available_time`** is at or before the query's `as_of_time`.

> **R2.** `decision_available_time` is not stored. It is **computed from the query's
> information-set profile** (§3). A record has no single availability time — it has
> several, and which one governs is a property of the question being asked.

> **R3.** A record whose governing availability time cannot be established under the
> requested profile is **not point-in-time under that profile**. It is excluded, or admitted
> only under an explicitly documented conservative lag. It is never admitted on the
> assumption that it was probably available.

> **R4.** A single result may not mix profiles, and may not mix revision views. Both are
> named in the manifest, and a run that cannot satisfy the requested combination is refused
> rather than silently degraded.

---

## 2. Terminology — exact meanings

Where a vendor uses one of these words differently, the vendor meaning is mapped at
ingestion and the vendor word is not propagated.

### 2.1 The four information times

This is the correction at the heart of revision 2. These are **four different facts about
the world**, and the first draft's single `source_available_time` silently picked whichever
one the ingestion code happened to have.

| Field | Meaning | Nullable |
|---|---|---|
| `public_available_time` | The instant the fact first became **publicly obtainable from the authoritative source** — an SEC acceptance datetime, an exchange dissemination, a press release. A property of the world, not of any vendor. | yes |
| `provider_available_time` | The instant **the selected provider first offered this record** in its feed or API. A property of the vendor. Frequently unknown, and its absence is itself information. | yes |
| `system_first_seen_time` | The instant **KalpaMani first held this record**. Always known, because we were there. | **no** |
| `ingestion_time` | The instant **this particular row was written**. Distinct from `system_first_seen_time`, which is the earliest receipt across the logical record's acquisition history; a rebuild writes a new row without changing when we first saw the data. | **no** |

And the derived one:

| Field | Meaning |
|---|---|
| `decision_available_time` | **The governing field for R1.** Computed per §3 from the active profile. Never stored as a column on a fact row; materialised only inside a keyed, versioned artifact that names its profile. |

Why this matters concretely: a vendor backfills ten years of history in a single file
delivered today. Under one reading that data was available throughout those ten years (the
world knew it). Under another it was available from the date the vendor started publishing
it. Under a third it was available today, because that is when we got it. **All three
readings are legitimate, and they answer different questions.** The first draft had no way to
say which one it meant.

### 2.2 Valid-time and identity fields

| Term | Meaning | Example |
|---|---|---|
| `observation_time` | The instant the fact was true or measured in the world. | a trade printed at 15:59:58 ET |
| `announcement_time` | For facts announced ahead of taking effect: when the announcement was made. | a split announced 2024-05-01 |
| `effective_date` | The business date to which a fact applies; a **date**, not an instant. | a split effective 2024-06-10 |
| `temporal_fact_class` | Which timing invariant applies to this entity (§7). | `RETROSPECTIVE` |
| `valid_from` / `valid_to` | Interval over which this version of the fact is current. | |
| `revision_sequence` | Monotonic integer per logical fact. `0` is the original observation. | a restatement becomes `1` |
| `as_of_time` | The caller cutoff. **Mandatory on every historical query.** | |
| `source_id` | Stable identity of the originating document or feed record. | an EDGAR accession number |
| `vendor_record_id` | The vendor row identity, retained for reconciliation, never branched on. | |
| `dataset_version` | Identity of the curated build a result came from. | `gold/2026.08.26.1` |

Vendor identifiers are *carried* for reconciliation and audit, never *branched on* by logic
above the boundary — [ADR-0002](../decisions/ADR-0002-broker-adapter-and-brokerage-boundary.md)
§4.

---

## 3. Information-set profiles

A profile answers one question: **whose information set are we simulating?**

| Profile | Simulates | `decision_available_time` = |
|---|---|---|
| **`PUBLIC_PIT`** | What the market could have known. | `public_available_time` |
| **`PROVIDER_REALISTIC_PIT`** | What a subscriber to our chosen provider could have known. | `max(public_available_time, provider_available_time)` |
| **`FORWARD_SYSTEM`** | What KalpaMani actually held. | `max(public_available_time, provider_available_time, system_first_seen_time)` |

The profiles are **strictly ordered in conservatism**: for any record,

```
PUBLIC_PIT  <=  PROVIDER_REALISTIC_PIT  <=  FORWARD_SYSTEM
```

so a result under a more conservative profile can never see more than a result under a less
conservative one. That ordering is asserted as an invariant, not assumed.

### 3.1 What each profile is for

| Profile | Legitimate use | Never valid for |
|---|---|---|
| `PUBLIC_PIT` | Exploratory factor research; academic-style questions about whether an effect exists in the market at all. | Any claim about what *this system* could have captured. |
| `PROVIDER_REALISTIC_PIT` | Backtests intended to inform capital deployment, where the provider is the one we would actually run on. | Any claim about latency or operational reality we have not measured. |
| `FORWARD_SYSTEM` | **Mandatory** for any forward, paper or micro-live validation claim. It is the only profile whose inputs we actually observed. | Long histories, since it cannot reach back before we existed. |

**Which profile governs production research is a decision gate, not settled here**
(ADR-0005 §17). The proposal is `PROVIDER_REALISTIC_PIT` for anything that informs capital,
`PUBLIC_PIT` permitted for exploration with the limitation declared, `FORWARD_SYSTEM`
required for forward validation. That proposal awaits the provider decision, because
`provider_available_time` is only obtainable for a provider we have chosen.

### 3.2 Unknown provider availability

`provider_available_time` will often be null — most vendors do not tell you when a row
entered their feed.

Under `PROVIDER_REALISTIC_PIT`, a null `provider_available_time` is resolved in exactly one
of two ways, chosen per dataset and recorded in configuration:

| Resolution | Effect |
|---|---|
| **EXCLUDE** | the record does not participate in the query |
| **DECLARE** | the record participates using `public_available_time`, and the run carries the limitation `PROVIDER_AVAILABILITY_UNKNOWN` naming the affected datasets and row counts |

There is no third option, and in particular there is no silent fallback. `DECLARE` is
honest about the fact that such a run is a `PUBLIC_PIT` result wearing a
`PROVIDER_REALISTIC_PIT` label for the rows in question, which is precisely what the
limitation token says.

### 3.3 Backfill semantics, per profile

The case that motivated the split. A vendor supplies, today, records describing events from
2015.

| Profile | Admissible in a 2015 query? |
|---|---|
| `PUBLIC_PIT` | **Yes** — *if and only if* authoritative public timing is proven for those records (§5 rule 1 or 2). Otherwise no. |
| `PROVIDER_REALISTIC_PIT` | **No** — a backfill may not become available before the provider supplied it. If `provider_available_time` is today, the record is inadmissible in 2015. If it is unknown, §3.2 applies. |
| `FORWARD_SYSTEM` | **No** — a backfill may never precede `system_first_seen_time`. |

**Mixing is forbidden.** A run that admits backfilled rows under `PUBLIC_PIT` reasoning while
labelling itself `PROVIDER_REALISTIC_PIT` is refused at manifest emission, not annotated.

---

## 4. The temporal model

Three independent axes, deliberately not collapsed:

```
VALID TIME       when the fact was true in the world
                 (observation_time, announcement_time, effective_date, fiscal period)

AVAILABILITY     when it could have been known -- by whom
                 (public_available_time, provider_available_time, system_first_seen_time)

DECISION TIME    the cutoff the caller is asking about
                 (as_of_time, resolved against a profile)
```

A query fixes decision time at `as_of_time` under a named profile, and is then free to range
over valid time:

```sql
SELECT ...
WHERE decision_available_time(:profile) <= :as_of
  AND effective_date BETWEEN :start AND :end
```

A restatement does not modify the original row. It is a **new row** for the same logical fact
with a higher `revision_sequence` and its own availability times. Nothing is ever updated in
place — which is what makes silent history rewriting structurally impossible rather than
merely discouraged.

---

## 5. Deriving each availability time

### 5.1 `public_available_time`

In priority order; the first rule that applies, wins.

| # | Situation | `public_available_time` |
|---|---|---|
| 1 | Authoritative machine timestamp exists (e.g. a filing acceptance datetime) | that timestamp, in UTC |
| 2 | The source supplies a publication timestamp **with** an unambiguous timezone | that timestamp, in UTC |
| 3 | Publication **date** only | end of that date in the venue timezone **plus the conservative lag** (§9) |
| 4 | Neither, but the record is tied to a session (e.g. a daily bar) | the session official close, plus the source's stated publication lag |
| 5 | None of the above | **null.** `availability_derivation = UNKNOWN`. Not point-in-time under any profile |

Rule 5 is the one that matters. "The vendor gave us history, so it must be historical" is the
reasoning that produces look-ahead, and it is the same shape of reasoning
[BLUEPRINT_ERRATA](../architecture/BLUEPRINT_ERRATA.md) E-001 already caught once in a
different domain: an assumption about an external system that nobody had tested.

### 5.2 `provider_available_time`

| # | Situation | `provider_available_time` |
|---|---|---|
| 1 | The provider stamps rows with a feed-publication or `lastupdated` time whose semantics are **documented and verified** | that timestamp, in UTC |
| 2 | The provider publishes dated file drops and we ingest from the drop | the drop timestamp |
| 3 | We have observed the record continuously since a known ingestion | `system_first_seen_time` is an upper bound; record it as such and mark the field derived |
| 4 | Otherwise | **null** → §3.2 |

Rule 1 carries a trap worth naming: a vendor `lastupdated` column usually means "when this
row last changed", not "when this row first appeared". The two coincide only for rows that
never changed. **Verifying which one a vendor means is a Phase-3A provider test**, not an
assumption ([implementation-plan.md](implementation-plan.md) §2).

### 5.3 `system_first_seen_time`

The `ingestion_time` of the earliest `ingestion_run` that delivered this logical record. Never
derived, never estimated, and never later than the row's own `ingestion_time`.

---

## 6. Revision views

The first draft said both "research defaults to as-originally-reported" and "the highest
`revision_sequence` admissible at `as_of`". Those are different rules and the draft applied
each in a different document. Corrected here.

**They are different questions**, and the fix is to stop having a default that answers only
one of them:

| View | Returns | Default for historical research |
|---|---|---|
| **`AS_KNOWN_AT_AS_OF`** | The **latest** revision whose `decision_available_time <= as_of`. If a restatement had already been published by `as_of`, it is returned; otherwise the original is. | **yes** |
| **`ORIGINAL_FILING_ONLY`** | `revision_sequence = 0` only, and only if admissible at `as_of`. Later restatements are invisible whatever the cutoff. | no |
| **`LATEST_RESTATED`** | The newest revision, **ignoring `as_of` entirely**. | **forbidden in research** |

`AS_KNOWN_AT_AS_OF` is the correct default because it is what a decision-maker at that moment
would actually have had in front of them — including any restatement already published. It is
*not* the same as "as originally reported", and the first draft conflated them.

`ORIGINAL_FILING_ONLY` remains available and is the right choice for questions specifically
about first-reported figures (a surprise measured against what was first announced, for
instance). It is a deliberate research choice, never a default.

### 6.1 `LATEST_RESTATED` is not point-in-time and is fenced off

- It is **unreachable from research and backtest code**, enforced by static test in the same
  way `data.live` is.
- Any result using it carries the mandatory limitation `NON_PIT_RESTATED_VIEW` and **may not
  be described as a backtest**.
- It exists for accounting-style analysis of restatement behaviour, which is a legitimate
  question that simply is not a simulation.

### 6.2 `revision_view` is required and has no default

Every accessor over a revisable fact takes `revision_view` explicitly, positionally, with no
default value — the same discipline `as_of` gets, and for the same reason. A default here is
a decision made silently by whoever wrote the accessor rather than by whoever asked the
question.

### 6.3 Vendor revision chronology must be proven, not assumed

Sharadar's `AR` (as-reported) and `MR` (most-recent-reported) dimensions establish that the
vendor distinguishes original from restated. **They do not, by themselves, establish that
every intermediate revision is retained with its own timestamp**, and revision 1 of this plan
overstated that.

`AS_KNOWN_AT_AS_OF` needs the full chronology: to know what was known on a Tuesday, you need
every revision published before that Tuesday, not just the first and the last. Where a
provider supplies only first-and-latest, `AS_KNOWN_AT_AS_OF` **degrades to a two-point
approximation** and the run carries `REVISION_CHRONOLOGY_INCOMPLETE`.

**Known-restatement qualification is therefore a BLOCKING provider test in Phase 3A/3B**
([implementation-plan.md](implementation-plan.md) §2, §3): take a company with a documented
multi-step restatement, and check whether the intermediate revisions are present with
distinct availability times. If they are not, that is a limitation of the data, declared —
not a limitation of the contract, waived.

---

## 7. Temporal fact classes

Not every fact is observed after it happens. A blanket "availability must not precede
observation" rule is wrong for anything announced in advance, and the first draft's check
would have blocked a perfectly correct scheduled-earnings row.

Every entity declares a `temporal_fact_class`:

| Class | Meaning | Timing invariant | Examples |
|---|---|---|---|
| **`RETROSPECTIVE`** | The fact is observed at or after it occurs. | `observation_time <= public_available_time` | price bars, executed trades, reported financials, an actual earnings release |
| **`ANNOUNCED_FORWARD`** | The fact is announced before it takes effect. **`effective_date` may legitimately be far later than availability.** | `announcement_time <= public_available_time`; **no constraint between `effective_date` and availability** | scheduled earnings dates, announced splits and dividends before ex-date, announced index or classification changes, future exchange sessions and holidays |
| **`SAMPLED_STATE`** | A state holding over an interval, observed by sampling. | `sample_time <= public_available_time` | borrow availability and fee, classification membership, shares outstanding |

The consequence: for `ANNOUNCED_FORWARD` facts, a query at `as_of` may correctly return a
fact about the future. A split announced on 1 May with a 10 June ex-date **is known on 2
May**, and refusing to return it would be its own error — the strategy needs to know that a
split is coming, because Blueprint §10.2 requires event-risk flags on every candidate.

What must never happen is the *adjustment* being applied before the announcement. That is a
separate rule and it lives in §8.

---

## 8. Adjusted prices — one design, stated once

Revision 1 contradicted itself: the schema said adjusted bars are never stored, the
implementation plan listed "adjusted bars" as gold contents. Resolved.

> **DECISION — Design A is normative.** An adjusted price series is **defined** as a pure
> function
>
> ```
> adjusted = f(raw_bars, corporate_actions admissible at as_of under the profile,
>               adjustment_policy)
> ```
>
> computed at query time. No adjusted series is a stored fact.

> **Materialisation is permitted only as a keyed, immutable, verifiable cache artifact** —
> never as an implicit mutable series. A cache artifact is identified by, and only by:
>
> | Key component |
> |---|
> | `adjustment_policy` (e.g. `SPLIT_ONLY`, `SPLIT_AND_DIVIDEND`, `TOTAL_RETURN`) |
> | `information_set_profile` |
> | `as_of_epoch` — the cutoff that fixed which actions are admissible |
> | `corporate_action_dataset_version` |
> | `raw_bar_dataset_version` |
> | `content_hash` of the produced series |
>
> Any cache artifact must reproduce bit-identically on recomputation from its key. A
> mismatch is a **BLOCKING** quality issue, not a cache miss.

`adjustment_mode` on the query interface therefore selects `RAW` or an
`ADJUSTED(adjustment_policy)`; there is no implicit adjustment and no unkeyed adjusted table
anywhere in the system.

The reason this is worth the ceremony: a split that had not been announced at `as_of` has not
adjusted anything, so "the adjusted close of AAPL on 2020-06-01" is not a number — it is a
number *per information set*. Storing one of them without its key is how a research
programme ends up with two different truths and no way to tell which it used.

---

## 9. The conservative-lag policy

Where `public_available_time` cannot be established exactly, a **documented,
version-controlled, per-domain lag** applies. A lag is a declared approximation, not a
default — recorded in configuration, carried in the dataset version, and reported with every
result that depended on it.

| Domain | Lag when exact public timing is unknown | Rationale |
|---|---|---|
| daily OHLCV | session close + 30 min | consolidated tape settles after the close |
| corporate actions | announcement date + 1 session | announcement *time* rarely published |
| fundamentals from filings | **none** — acceptance datetime is authoritative | exact, machine-generated |
| fundamentals with no filing link | filing date + 1 session | vendor processing lag unknown |
| earnings announcement, no verified time | **next session open** after the reported date | refuses to assume before-market |
| analyst estimate snapshots | snapshot date + 1 session | consensus files are end-of-day products |
| borrow availability / fee | **no lag is acceptable** — see below | |
| classification changes | effective date + 1 session | |

**Borrow is deliberately absent a lag.** There is no conservative lag that turns *current*
borrow data into *historical* borrow data; the value simply did not exist for that date. A lag
can correct a timing error; it cannot manufacture a missing observation. That is why borrow is
a Phase 3C qualification gate and not a lag-policy row.

Lags apply to `public_available_time` only. **A lag may never be used to invent a
`provider_available_time`** — that field is either known, or null and handled by §3.2.

---

## 10. Fail-closed rules

Consistent with ADR-0004 §5 — *"It never assumes 'no record' means 'nothing happened'"*.

These are errors, not warnings, and abort the query rather than returning a degraded result:

1. `as_of_time` absent from a historical query.
2. `information_set_profile` absent from a historical query.
3. `revision_view` absent from a query over revisable facts.
4. `revision_view = LATEST_RESTATED` reached from research or backtest code.
5. `as_of_time` later than the dataset build time.
6. A record with `availability_derivation = UNKNOWN` participating in a point-in-time query.
7. A requested `as_of` earlier than the dataset declared coverage start.
8. Any `BLOCKING` data-quality issue open against a dataset the query touches.
9. A universe query for a date with no `universe_membership` snapshot.
10. Records resolved under **more than one profile** within a single result.
11. `PROVIDER_REALISTIC_PIT` requested where `provider_available_time` is null and the
    dataset resolution is neither `EXCLUDE` nor `DECLARE`.
12. A schema version unrecognised by the reading code.
13. A checksum mismatch between a curated table and the artifacts it declares.
14. An adjusted-cache artifact that does not reproduce from its key.

Rule 7 deserves emphasis. **An empty result and a refusal are different answers**, and a data
layer that returns the first when it means the second produces a backtest that looks merely
unprofitable rather than broken.

---

## 11. Universe queries and survivorship

`get_security_universe(as_of, profile)` returns membership **as recorded for that date**, from
a stored snapshot. It is never recomputed from current data, and never derived by filtering
today's listed securities.

- A security delisted before `as_of` **is absent**. One delisted after `as_of` but active then
  **is present**, including its subsequent delisting.
- Eligibility thresholds are evaluated using data **admissible at that date under that
  profile** — which means a universe snapshot is profile-specific and is keyed by profile.
- The snapshot records the `universe_definition_version` that produced it. Changing the rule
  produces a new version; it does not retroactively change history.

Blueprint §4's thresholds — NYSE/NASDAQ common stock, price > $10, cap > ~$1.5B,
ADDV > ~$25M, > 250 sessions of history — are the initial rule, and are parameters of a
versioned definition rather than constants in code.

---

## 12. Hard cases

### 12.1 Late-arriving data
`system_first_seen_time` exceeds `public_available_time` by more than the dataset's declared
latency budget. **Accepted and flagged.** Stored with true times so history stays correct;
`WARNING` raised. If it breaches the freshness bound of a dataset used for **live** decisions,
severity escalates to `BLOCKING` — stale data driving a live scan is a different failure from
stale data in a backtest.

### 12.2 Corrections
A new revision row. The original is never overwritten. A correction carrying no availability
timestamp of its own inherits `system_first_seen_time` for `public_available_time` — the
conservative choice, since we demonstrably did not have it earlier.

### 12.3 Restatements
New revision row keyed to the same fiscal period, carrying the restating filing's acceptance
time. Visibility is then a question of `revision_view` (§6), not of a hidden default.

### 12.4 Vendor backfills
See §3.3. This is the case the profile model exists for.

### 12.5 Conflicting timestamps
Two sources disagree about when something was published. **Fail toward the later time.**
Record both, raise a `WARNING`, use the later — the later time is the one that cannot create
look-ahead. Systematic disagreement between two sources on the same domain is `BLOCKING`,
because it means at least one is wrong about something structural.

### 12.6 Timezone normalization
Everything is stored in **UTC**, as an aware instant. Local wall-clock times are never stored
without an offset. Market-facing logic converts to `America/New_York` at the edge and nowhere
else. `effective_date` and other business dates stay **dates** and are never silently promoted
to midnight-anything.

### 12.7 Market-session dates versus calendar dates
A session is identified by its **session date from the exchange calendar**, not by the UTC
calendar date of any instant within it. These differ routinely (a 20:00 ET print is the next
UTC day) and the difference is a full day of look-ahead if confused. All bar and session joins
key on session date, never on a truncated UTC timestamp.

### 12.8 After-hours announcements
An announcement at 16:05 ET is available at 16:05 ET — not at the next open, and not on the
session that just ended. The contract stores the true instant. What downstream logic may *do*
with it is a strategy decision (Blueprint §5.3), not a data-layer one.

### 12.9 Weekend and holiday publication
Publication does not require an open market. A Saturday 8-K is available Saturday. The first
*actionable* session is a separate derived quantity (`next_tradable_session`), computed from
the calendar and never conflated with availability.

### 12.10 Daylight-saving transitions
Store UTC; convert with a real tz database (`zoneinfo`), never a fixed offset; never hardcode
`-05:00` or `-04:00`. Treat 02:00–03:00 local on a spring-forward date as non-existent, and
01:00–02:00 on a fall-back date as ambiguous, resolving ambiguity to the **later**
(post-transition) instant, consistent with §12.5.

Half-days and early closes come from the calendar domain, not from assumption — the same
correction [ADR-0004](../decisions/ADR-0004-deterministic-order-identity-idempotency-and-execution-lifecycle.md)
§14 already had to make once, when a hardcoded 15:30 bound would have permitted an entry one
minute before a 13:00 early close.

---

## 13. The anti-lookahead query interface

Every historical accessor takes an explicit `as_of` **and** an explicit
`information_set_profile`. Accessors over revisable facts additionally take `revision_view`.
No defaults. No `latest` convenience. No overload without them.

```python
get_security_universe(as_of, profile)                          -> UniverseSnapshot
get_price_history(security_id, start, end,
                  adjustment_mode, as_of, profile)             -> BarSeries
get_fundamental_snapshot(security_id, period,
                         as_of, profile, revision_view)        -> FundamentalFact
get_estimate_snapshot(security_id, estimate_period,
                      as_of, profile, revision_view)           -> EstimateSnapshot
get_revision_history(security_id, start, end, as_of, profile)  -> RevisionSeries
get_earnings_event(security_id, event_id, as_of, profile)      -> EarningsEvent
get_borrow_snapshot(security_id, as_of, profile)               -> BorrowSnapshot
get_classification(security_id, as_of, profile)                -> Classification
```

Enforced structurally, by test, in the manner ADR-0004 §10 already uses for the execution
boundary — *"Enforced by test, not convention"*:

- **`as_of`, `profile` and `revision_view` are required and have no defaults.** A static test
  asserts no accessor declares any of them with a default value.
- **No `latest` path exists in research code.** A static scan forbids the identifiers
  `latest`, `current`, `most_recent` and `today` in research and backtest packages, and
  forbids `LATEST_RESTATED` there entirely.
- **`adjustment_mode` is required and explicit** (§8).
- **Results carry their provenance** — `dataset_version`, `as_of`, `profile`, `revision_view`
  and every lag applied. A result that cannot say where it came from is not a result.

### 13.1 Live versus historical

```
kalpamani.data.pit     historical, as_of + profile mandatory   research and backtest
kalpamani.data.live    current, as_of forbidden                live scanning only
```

Two packages, not one package with a flag. A flag is a thing that can be set wrongly; a
missing import is a thing that fails in CI. Research code importing `data.live` is a
static-test failure, the same shape as ADR-0004 §10's rule that strategy modules cannot import
execution.

---

## 14. How LEAN consumes this

Blueprint §26 and ADR-0002 §13: broker-supplied market data may be used for operational
verification, and is **never** the basis for universe ranking, backtests or any performance
claim.

```
PIT layer (authoritative)
    -> exports versioned, date-keyed, profile-keyed artifacts
        -> LEAN consumes them as custom data / universe files
            -> LEAN IBKR feed is used ONLY for live execution reality
```

- **LEAN universe selection reads an exported historical membership file keyed by session date
  and profile.** It does not query a live universe API and does not filter a current list.
  This is the highest-risk integration point for survivorship leakage.
- **Fundamental, estimate and event data reach LEAN as custom data carrying explicit
  availability times**, so LEAN's own event scheduling honours them.
- **Price data for backtests comes from the curated layer**, cross-validated against an
  independent source where one is licensed ([data-quality-plan.md](data-quality-plan.md)).
  Disagreement is a quality issue, not something to silently prefer one side of.
- **IBKR data is never written into the research store.** Phase 1 established the pattern —
  SPY delayed data proved connectivity and nothing else.

The export step is deliberate. It makes a backtest's inputs a **materialised, versioned,
checksummed artifact** rather than the live result of a query that might behave differently
tomorrow — the difference between a reproducible result and a result that happened to
reproduce.
