# Phase 3 — Conceptual Schemas / Data Contracts

**Status: PROPOSED — planning only. Nothing is implemented.**

These are **vendor-neutral data contracts**, not DDL and not a vendor mapping. Per the task
constraint, they are deliberately not overfitted to any provider before the provider decision
is made ([provider-evaluation.md](provider-evaluation.md) is a *proposal*, not a purchase).

Types are conceptual: `instant` is a timezone-aware UTC timestamp; `date` is a calendar date
with no time component and is never silently promoted to an instant
([pit-data-contract.md](pit-data-contract.md) §12.6).

> **Revision 6 (2026-08-26).** `price_bar` splits so no derived row sits inside a
> `RETROSPECTIVE` source entity (§6, §6a); `adjusted_bar_artifact` carries a complete derived
> envelope with one normative name per field (§7a); and the remaining source entities get
> explicit, non-nullable temporal anchors (§2, §5, §7, §15).
>
> **Revision 5 (2026-08-26).** The two envelopes become **mutually exclusive** (§0.1c);
> derived artifacts declare **`output_validity`** instead of borrowing a source temporal class;
> exact and bound derivations get **separate enums** (§0.2); `security` splits into canonical
> identity and time-varying attributes (§1, §1a); the internally-generated summary leaves
> `source_document` for `research_summary_artifact` (§15a); `earnings_schedule` splits into
> announcement and estimate (§10, §10e); classification gains a per-row fact kind (§14); and
> `dataset_version` names `resolved_profile` (§18).
>
> **Revision 4 (2026-08-26).** The **atomic-fact rule** (§0.0) is added, and the schemas that
> broke it are split: `earnings_event` becomes five entities (§10), reported and derived
> fundamentals separate (§9, §9a), `universe_membership` becomes an explicit derived artifact
> (§4), and `source_document` and `price_bar` carry origin **per row** (§15, §6). A
> **derived envelope** (§0.1b) replaces revision 3's unrepresentable "inherited" origin, and
> exact provider/public times are separated from conservative upper bounds (§0.1).
>
> **Revision 3 (2026-08-26).** The envelope gains **`information_origin`** (§0.1a), which
> decides which profiles a record is eligible for and which of its times may legitimately be
> null, and the derivation enums distinguish *failed to establish* from *does not exist*.
>
> **Revision 2 (2026-08-26).** The envelope no longer carries a single
> `source_available_time`. It carries the four distinct information times from
> [contract §2.1](pit-data-contract.md), and the governing `decision_available_time` is
> **computed per profile, never stored on a fact row**. Every entity now declares a
> `temporal_fact_class`. Adjusted bars are resolved as a keyed cache artifact (§7a).

---

## 0.0 The atomic-fact rule

> **One row has exactly one `information_origin`, exactly one availability envelope, and
> exactly one temporal declaration** — a `temporal_fact_class` if it is a source fact, an
> `output_validity` if it is a derived artifact. A row may not combine independently changing
> facts merely because they share an event or a security identity.

**A declared class must have its anchor.** A source row declaring `RETROSPECTIVE` carries an
`observation_time`; `ANNOUNCED_FORWARD` carries an `announcement_time`; `SAMPLED_STATE` carries
a `sample_time`. A class without its anchor is a class that cannot be checked, and revision 4
had four of them.

The test: **if two values can change at different times, for different reasons, from different
sources, they are two facts.** They may share an identifier; they may not share an envelope.

Revision 3 broke this in four places, and each is fixed below: `earnings_event` (§10) packed a
scheduled date, a realised release, a provider consensus and a computed surprise into one row;
`fundamental_fact` (§9) labelled derived TTM values as authoritative public facts;
`universe_membership` (§4) claimed an "inherited" origin the closed enum could not express; and
`source_document` and `price_bar` declared a single origin for rows whose origins genuinely
differ.

---

## 0. The common envelope

Written once here, referenced as **`«envelope»`** rather than repeated twenty times. There are
**two** envelopes — a source envelope (§0.1) and a derived envelope (§0.1b) — and
`information_origin` selects between them.

### 0.1 Information times

| Field | Type | Meaning |
|---|---|---|
| `public_available_time` | instant? | When the fact first became publicly obtainable from the authoritative source. Derived per [contract §5.1](pit-data-contract.md). **Nullable — and what a null means depends on `information_origin`**: for `AUTHORITATIVE_PUBLIC` it means we failed to establish a time that exists, and the row is unusable everywhere; for the other origins it means no such time exists, and the row stays usable where §0.1a allows. |
| `provider_available_time` | instant? | When the selected provider first offered this record. Derived per [contract §5.2](pit-data-contract.md). **Nullable**; under `PROVIDER_REALISTIC_PIT` a null is resolved by `EXCLUDE`, `BOUND` or `DOWNGRADE` ([contract §3.3](pit-data-contract.md)). |
| `public_available_upper_bound` | instant? | A time the fact was certainly public **by**, when the exact instant is unknown but bounded — a correction, for example ([contract §12.2](pit-data-contract.md)). **Never written into the exact field.** |
| `provider_available_upper_bound` | instant? | A time the provider certainly offered the record **by**. Set by the `BOUND` resolution from `system_first_seen_time`. **`provider_available_time` stays null.** |
| `system_first_seen_time` | instant | When KalpaMani first held this record. Never null, never estimated. |
| `ingestion_time` | instant | When *this row* was written. A rebuild writes a new row without changing `system_first_seen_time`. |

**Exact and bound are different fields and never overwrite one another**
([contract §2.6](pit-data-contract.md)). Revision 3 wrote `system_first_seen_time` into
`provider_available_time` under `BOUND`, which destroyed the provenance that field exists to
carry and made a bounded row indistinguishable from a precisely-stamped one. The governing
computation reads exact first, then bound, and the manifest records which was used.

**`decision_available_time` is not a column.** It is computed at query time from the active
`resolved_profile` ([contract §3](pit-data-contract.md)). Storing it would bake one
profile into the data and is precisely the conflation revision 1 committed.

### 0.1a Information origin

**New in revision 3.** Decides which profiles a record can be served under, and which of its
times may legitimately be null ([contract §2.3, §3.1](pit-data-contract.md)).

| Field | Type | Meaning |
|---|---|---|
| `information_origin` | enum | `AUTHORITATIVE_PUBLIC` · `PROVIDER_DERIVED` · `SYSTEM_OBSERVED` · **`DERIVED_ARTIFACT`**. **Required on every row; there is no default.** The first three select the source envelope (§0.1); the fourth selects the derived envelope (§0.1b). |

| `information_origin` | `public` | `provider` | `seen` | eligible profiles |
|---|---|---|---|---|
| `AUTHORITATIVE_PUBLIC` | **required** | optional | required | all three |
| `PROVIDER_DERIVED` | **must be null** | **required** | required | `PROVIDER_REALISTIC_PIT`, `FORWARD_SYSTEM` |
| `SYSTEM_OBSERVED` | null | null | **required** | `FORWARD_SYSTEM` only |
| `DERIVED_ARTIFACT` | **null** | **null** | **null** | intersection of its inputs; always `FORWARD_SYSTEM` |

Origin is declared **per entity** below where every row of that entity shares one, and **per
row** where they genuinely differ: `borrow_snapshot` (§13), `classification_history` (§14),
`source_document` (§15) and `price_bar` (§6).

### 0.1b The derived envelope — `DERIVED_ARTIFACT`

A derived row carries **none** of the source times. It carries lineage instead
([contract §2.5](pit-data-contract.md)):

| Field | Type | Meaning |
|---|---|---|
| `lineage` | list | **Complete** input lineage: entity, `dataset_version`, and row selector or upstream `artifact_id` per input. The set a rebuild would read, not a summary. |
| `artifact_first_built_time` | instant | When the artifact was **first** built. A rebuild from the same lineage does not move it. |
| `derivation_spec_version` | string | Version of the computation that produced it. |
| `artifact_content_hash` | string | SHA-256 of the produced value or series. |

```
PUBLIC_PIT             dat = max over inputs of dat(input, PUBLIC_PIT)
PROVIDER_REALISTIC_PIT dat = max over inputs of dat(input, PROVIDER_REALISTIC_PIT)
FORWARD_SYSTEM         dat = max( max over inputs of dat(input, FORWARD_SYSTEM),
                                  artifact_first_built_time )
```

**Eligibility is the intersection of its inputs' eligibility.** A derived value never invents
public or provider availability, and never becomes eligible under a profile one of its inputs
is barred from.

### 0.1c The two envelopes are mutually exclusive

Revision 4 described the derived envelope as an alternative but left it a subset of the source
envelope with fields it "must not carry", so a derived row still had to be validated as a
malformed source row. They are now disjoint, and the quality checks branch on origin before
anything else ([data-quality-plan.md](data-quality-plan.md) §4.0).

| | SOURCE fact | DERIVED artifact |
|---|---|---|
| `information_origin` | `AUTHORITATIVE_PUBLIC` · `PROVIDER_DERIVED` · `SYSTEM_OBSERVED` | `DERIVED_ARTIFACT` |
| `public_available_time` / `_upper_bound` | per origin | **absent** |
| `provider_available_time` / `_upper_bound` | per origin | **absent** |
| `system_first_seen_time` | **required** | **absent** |
| temporal declaration | one `temporal_fact_class` + its anchor | one `output_validity` + its field(s) |
| `lineage` | absent | **required, complete** |
| `artifact_first_built_time` | absent | **required** |
| `derivation_spec_version` · `artifact_content_hash` | absent | **required** |
| `ingestion_time` · `dataset_version` · `quality_status` · `provider` | present | present |

The last row is the only overlap: those are **physical row properties**, not claims about when
anyone could have known anything.

### 0.1d `output_validity` — what a derived artifact is *about*

| `output_validity` | Required field(s) | Used by |
|---|---|---|
| `SESSION_SCOPED` | `effective_session` | §4 `universe_membership` |
| `INTERVAL` | `valid_time_start`, `valid_time_end` | §7a `adjusted_bar_artifact`, rolling and windowed factors |
| `PERIOD_END` | `period_end` | §9a `fundamental_derived_fact` |
| `EVENT_REFERENCED` | `observation_reference` | §10c `earnings_surprise_artifact`, §15a `research_summary_artifact` |

**`output_validity` never participates in an availability computation.** It says what period the
output describes; availability comes from lineage plus `artifact_first_built_time` under
`FORWARD_SYSTEM`, and from lineage alone otherwise. Keeping those apart is why the derived
envelope exists.

### 0.2 Temporal classification

| Field | Type | Meaning |
|---|---|---|
| `temporal_fact_class` | enum | `RETROSPECTIVE` · `ANNOUNCED_FORWARD` · `SAMPLED_STATE` — selects which timing invariant applies ([contract §7](pit-data-contract.md)). Declared per entity, not per row, except where noted. |
| `public_time_derivation` | enum | How the **exact** `public_available_time` was established: `AUTHORITATIVE_TIMESTAMP` · `VENDOR_TZ_TIMESTAMP` · `UNKNOWN` · `NOT_APPLICABLE`. `UNKNOWN` = a public time exists and we failed to establish it (**unusable**); `NOT_APPLICABLE` = no public time exists for this origin (**usable where §0.1a allows**). |
| `public_bound_derivation` | enum | How `public_available_upper_bound` was derived: `DATE_PLUS_LAG` · `SESSION_CLOSE_PLUS_LAG` · `FIRST_SEEN_UPPER_BOUND` · `NONE` |
| `provider_time_derivation` | enum | How the **exact** `provider_available_time` was established: `VENDOR_STAMPED` · `FILE_DROP` · `UNKNOWN` · `NOT_APPLICABLE` |
| `provider_bound_derivation` | enum | How `provider_available_upper_bound` was derived: `FIRST_SEEN_UPPER_BOUND` · `DELIVERY_WINDOW` · `NONE` |

**Four enums, not two.** Revision 4 had one enum per axis mixing exact and approximate members
(`AUTHORITATIVE_TIMESTAMP` alongside `DATE_PLUS_LAG`), which is how a lag-derived value ended up
in a field documented as exact. Exact derivations name exact fields; bound derivations name
bound fields; nothing in one vocabulary can write the other's field.
| `applied_lag` | duration? | Non-null only when `DATE_PLUS_LAG`. Surfaced in the research manifest. |

### 0.3 Version and provenance

| Field | Type | Meaning |
|---|---|---|
| `valid_from` / `valid_to` | instant / instant? | Interval this version is current for. |
| `revision_sequence` | int | 0 = original. Monotonic per logical fact. |
| `source_id` | string | Originating document / feed record identity. |
| `vendor_record_id` | string? | Vendor row identity. Carried, never branched on (ADR-0002 §4). |
| `provider` | string | Which vendor supplied this row. |
| `dataset_version` | string | The curated build this row belongs to. |
| `quality_status` | enum | `OK` · `SUSPECT` · `QUARANTINED` |

### 0.4 Load-bearing envelope rules

- **`public_time_derivation = UNKNOWN` may never participate in a point-in-time query**
  ([contract §10](pit-data-contract.md) rule 6). `NOT_APPLICABLE` is not `UNKNOWN`, and the two
  are separate enum members precisely so the refusal is mechanical rather than a judgement.
- **`provider_time_derivation = UNKNOWN` under `PROVIDER_REALISTIC_PIT`** triggers the
  dataset's declared `EXCLUDE`, `BOUND` or `DOWNGRADE` resolution — never a silent fallback,
  and never the withdrawn `DECLARE`.
- **A row is served only under a profile its origin is eligible for** (§0.1a). Ineligible rows
  are excluded and counted, never substituted.
- **`quality_status = QUARANTINED` rows are excluded from every research query.** Retained,
  not deleted — deleting the evidence of a data problem is how the same problem recurs.
- **The ordering `public <= provider <= system_first_seen` is asserted only over the times a
  record actually has**, per its origin. Violations are graded in
  [data-quality-plan.md](data-quality-plan.md) §4. Asserting it across a time the record
  legitimately lacks is a malformed comparison, not a violation.

---

## 1. `security` — `EVENT_REFERENCED` · **`DERIVED_ARTIFACT`**

**Canonical internal identity only.** The `security_id` is *ours*: we assign it by resolving
external evidence — listings, filings, vendor identifiers — into one durable identity. That is a
derivation, not an observation, and revision 4 labelled it `AUTHORITATIVE_PUBLIC` alongside
externally-sourced attributes that change on their own schedule.

| Field | Type | Notes |
|---|---|---|
| `security_id` | string, **PK** | Internal, permanent, opaque. **Never a ticker.** |
| `observation_reference` | list | the listing and filing rows that established this identity |
| `«derived envelope»` | | `lineage` over those rows; `artifact_first_built_time` = when we assigned the id |

**`is_common_stock_eligible` is gone from here**, and that is the substantive fix. Eligibility
is a *rule applied to attributes*, not a property of a security — it depends on the Blueprint §4
thresholds, which are versioned and can change without the company changing at all. It now lives
where the rule lives: the versioned eligibility derivation behind `universe_membership` (§4),
keyed by `universe_definition_version`.

## 1a. `security_attribute` — `SAMPLED_STATE` · **origin per row**

Externally sourced, time-varying attributes. Separate from §1 because they change on their own
schedule, from their own sources, with their own availability.

| Field | Type | Notes |
|---|---|---|
| `security_id` | FK, **PK part** | |
| `attribute` | string, **PK part** | `security_type` · `country_of_incorporation` · `figi` · `cusip` · `isin` |
| `valid_from` | date, **PK part** | |
| `valid_to` | date? | |
| `value` | string | |
| `sample_time` | instant | the `SAMPLED_STATE` anchor |
| `information_origin` | enum | `AUTHORITATIVE_PUBLIC` where the attribute comes from a filing or exchange notice; `PROVIDER_DERIVED` where a vendor assigned it |
| `«envelope»` | | source envelope |

`figi` is openly licensed; `cusip` and `isin` are **licence-gated** and never a join key.

## 2. `listing` — **class per row** · `AUTHORITATIVE_PUBLIC`

| Field | Type | Notes |
|---|---|---|
| `listing_id` | string, **PK** | |
| `security_id` | FK → `security` | |
| `exchange` | enum | `NYSE` · `NASDAQ` · `NYSE_AMERICAN` · `OTC` · … |
| `listing_start` / `listing_end` | date / date? | |
| `delisting_reason` | enum? | `MERGER` · `ACQUISITION` · `BANKRUPTCY` · `DEFICIENCY` · `VOLUNTARY` · `UNKNOWN` |
| `successor_security_id` | FK? | M&A continuity |
| `listing_fact_kind` | enum, **PK part** | `STATE` · `CHANGE_ANNOUNCEMENT` |
| `observation_time` | instant? | **required** for `STATE` — when the listing or delisting took place |
| `announcement_time` | instant? | **required** for `CHANGE_ANNOUNCEMENT` — when the venue announced it |
| `temporal_fact_class` | enum | **per row**: `STATE` → `RETROSPECTIVE`; `CHANGE_ANNOUNCEMENT` → `ANNOUNCED_FORWARD` |
| `«envelope»` | | source envelope |

**Exactly one anchor applies per row**, selected by `listing_fact_kind` — which is a primary-key
part so the two facts cannot collapse into one row. Revision 5 declared this entity
`RETROSPECTIVE` while its prose said some rows are announced ahead of the effective date; a
delisting announced on Monday and effective Friday is two different facts, and the anchor a
check reads depends on which one the row is.



## 3. `ticker_history` — `RETROSPECTIVE` · `AUTHORITATIVE_PUBLIC`

| Field | Type | Notes |
|---|---|---|
| `security_id` | FK → `security` | |
| `ticker` | string | |
| `valid_from` / `valid_to` | date / date? | **PK is (`ticker`, `valid_from`)** — tickers are recycled |
| `change_reason` | enum? | `RENAME` · `MERGER` · `REVERSE_SPLIT` · `EXCHANGE_MOVE` |
| `observation_time` | instant | the `RETROSPECTIVE` anchor — when the mapping took effect |
| `«envelope»` | | |

**Invariant.** For any (`ticker`, `date`) there is at most one `security_id`. Overlap is
`BLOCKING` — an overlap means every join on that ticker is ambiguous.

## 4. `universe_membership` — `SESSION_SCOPED` · **`DERIVED_ARTIFACT`**

The survivorship control. **Stored per session, never recomputed at query time.**

| Field | Type | Notes |
|---|---|---|
| `session_date` | date, **PK part** | From `market_session`; also the `SESSION_SCOPED` `effective_session` |
| `security_id` | FK, **PK part** | |
| `universe_definition_version` | string, **PK part** | Changing the rule creates a version |
| `resolved_profile` | enum, **PK part** | Eligibility is evaluated on admissible data, so membership is profile-specific — and it is keyed by the profile the build **resolved** to |
| `is_member` | bool | |
| `price_at_eval` / `market_cap_at_eval` / `addv_at_eval` | decimal | The values that produced the decision |
| `history_sessions_at_eval` | int | |
| `exclusion_reason` | enum? | `PRICE` · `MARKET_CAP` · `ADDV` · `HISTORY` · `EXCHANGE` · `SECURITY_TYPE` |
| `is_common_stock_eligible` | bool | **moved here from §1.** Evaluated from `security_attribute` under `universe_definition_version` — a versioned rule, not a property of the company |
| `«envelope»` | | |

The stored evaluation inputs are not redundant. They make a membership decision auditable
years later, and let a quality check confirm the rule was applied to admissible data rather
than to current data.

**A universe snapshot is a derived artifact, and revision 3 could not say so.** It claimed the
origin was "inherited", which the closed enum had no value for. It now carries
`information_origin = DERIVED_ARTIFACT` and the derived envelope (§0.1b): complete `lineage`
over the price, shares-outstanding and listing rows that produced each decision, plus
`artifact_first_built_time`.

Eligibility is the **intersection** of its inputs'. In practice those inputs are all
`AUTHORITATIVE_PUBLIC`, so snapshots are normally eligible everywhere — but the rule is stated
because a future eligibility criterion sourced from a proprietary feed would narrow the whole
universe to `PROVIDER_REALISTIC_PIT` and below, silently, and this is where that would show up.

## 5. `market_session` — `ANNOUNCED_FORWARD` · `AUTHORITATIVE_PUBLIC`

Exchange calendars are published in advance. A 2027 holiday schedule known in 2026 is a
correct, non-leaking fact — which is exactly why the blanket rule from revision 1 was wrong.

| Field | Type | Notes |
|---|---|---|
| `exchange` | enum, **PK part** | |
| `session_date` | date, **PK part** | The canonical session key |
| `regular_open` / `regular_close` | instant | UTC; **derived from the calendar**, never assumed |
| `extended_open` / `extended_close` | instant | |
| `is_half_day` / `is_holiday` | bool | ADR-0004 §14 exists because this was once assumed away |
| `announcement_time` | instant? | **exact** — when the calendar revision publishing this session was released |
| `announcement_time_upper_bound` | instant? | **conservative** — for a date-only calendar publication |
| `announcement_bound_derivation` | enum? | `DATE_PLUS_LAG` · `NONE` |
| `«envelope»` | | |

**An `ANNOUNCED_FORWARD` row must have a usable anchor, not merely a nullable one.** Exactly one
of `announcement_time` (exact) or `announcement_time_upper_bound` (conservative, for a date-only
announcement) is **required** — never neither. The bound is derived like any other
([contract §5.1](pit-data-contract.md)): end of the announcement date in the venue timezone plus
the declared lag, recorded as `announcement_bound_derivation = DATE_PLUS_LAG`.

Revision 5 claimed every declared class has its anchor while leaving this field nullable with no
alternative, so a date-only announcement satisfied the letter of the rule and had nothing for the
class invariant to read.


## 6. `price_bar` — `RETROSPECTIVE` · **source facts only, origin per row**

| Field | Type | Notes |
|---|---|---|
| `security_id` | FK, **PK part** | |
| `session_date` | date, **PK part** | |
| `resolution` | enum, **PK part** | `DAILY` · `MINUTE` |
| `open` / `high` / `low` / `close` | decimal | **RAW / unadjusted.** The traded prices. |
| `volume` | integer | |
| `trade_count` | integer? | |
| `vwap` | decimal? | Where licensed |
| `is_stale` / `had_halt` | bool | A non-trading day is not a zero |
| `observation_time` | instant | the `RETROSPECTIVE` anchor — the session close the bar summarises |
| `bar_construction` | enum | `OFFICIAL_DISSEMINATED` · `PROVIDER_AGGREGATED` — **source constructions only** |
| `information_origin` | enum | **per row**, per the table below |
| `«envelope»` | | source envelope |

**Not every bar is an authoritative public fact.** A consolidated-tape daily bar disseminated by
the SIP is; a bar the vendor aggregated from its own trade collection is the vendor's
construction.

| `bar_construction` | `information_origin` | Meaning |
|---|---|---|
| `OFFICIAL_DISSEMINATED` | `AUTHORITATIVE_PUBLIC` | the venue or SIP published this bar |
| `PROVIDER_AGGREGATED` | `PROVIDER_DERIVED` | the provider built it from trades it collected |

**`SYSTEM_AGGREGATED` is gone from this entity**, and that is the revision-6 correction.
Revision 5 listed it here mapping to `DERIVED_ARTIFACT`, which put a derived row inside an
entity declared `RETROSPECTIVE` and carrying the source envelope — a row that could satisfy
neither. A bar *we* resampled is not a source fact at all; it is §6a.

**Which construction applies to purchased bars is established during provider qualification,
not assumed** ([implementation-plan.md](implementation-plan.md) §2, test P9). It matters: if the
daily bars turn out to be `PROVIDER_AGGREGATED`, then **price data itself is ineligible under
`PUBLIC_PIT`**, and so is every artifact built on it — a far larger consequence than the
estimates gap.

**Only raw bars are facts.** Adjusted series are computed
([contract §8](pit-data-contract.md)) and, if materialised, live in §7a — never here, and never
as an extra column.

## 6a. `aggregated_price_bar_artifact` — `INTERVAL` · **`DERIVED_ARTIFACT`**

Bars **we** built by resampling finer-grained rows we hold — a daily bar rolled up from minute
data, for instance.

| Field | Type | Notes |
|---|---|---|
| `artifact_id` | string, **PK** | derived hash of the key below — not generated |
| `security_id_scope` | string, **key** | universe version or explicit id set |
| `target_resolution` | enum, **key** | `DAILY` · `HOUR` |
| `source_resolution` | enum, **key** | the finer resolution consumed |
| `resolved_profile` | enum, **key** | |
| `valid_time_start` / `valid_time_end` | date / date | the `INTERVAL` validity fields |
| `information_origin` | enum | `DERIVED_ARTIFACT` |
| `output_validity` | enum | `INTERVAL` |
| `lineage` | list | **complete** — the §6 `price_bar` rows consumed, by `dataset_version` and selector |
| `artifact_first_built_time` | instant | when first built; a rebuild from identical lineage does not move it |
| `derivation_spec_version` | string | the resampling rule |
| `artifact_content_hash` | string | SHA-256 of the produced series |

Its availability is the max over the bars it consumed, plus `artifact_first_built_time` under
`FORWARD_SYSTEM`, and **its eligibility is the intersection of theirs** — resampling
provider-aggregated minute bars cannot produce a publicly-available daily bar.

## 7. `corporate_action` — `ANNOUNCED_FORWARD` · `AUTHORITATIVE_PUBLIC`

| Field | Type | Notes |
|---|---|---|
| `action_id` | string, **PK** | |
| `security_id` | FK | |
| `action_type` | enum | `SPLIT` · `REVERSE_SPLIT` · `DIVIDEND` · `SPECIAL_DIVIDEND` · `SPINOFF` · `MERGER` · `RIGHTS` · `SYMBOL_CHANGE` · `DELISTING` |
| `announcement_date` | date? | Nullable; its absence is itself information |
| `announcement_time` | instant? | **exact** anchor for this class |
| `announcement_time_upper_bound` | instant? | **conservative** anchor — end of `announcement_date` in the venue timezone plus the declared lag |
| `announcement_bound_derivation` | enum? | `DATE_PLUS_LAG` · `NONE` |
| `ex_date` / `record_date` / `pay_date` / `effective_date` | date? | **May be far later than availability. That is correct, not a violation.** |
| `ratio` / `cash_amount` | decimal? | |
| `«envelope»` | | |

**An `ANNOUNCED_FORWARD` row must have a usable anchor, not merely a nullable one.** Exactly one
of `announcement_time` (exact) or `announcement_time_upper_bound` (conservative, for a date-only
announcement) is **required** — never neither. Revision 5 claimed every declared class has its
anchor while leaving this field nullable with no alternative, so a date-only corporate action
satisfied the letter of the rule and had nothing for the class invariant to read.

**Availability rule.** `public_available_time` derives from `announcement_time`/
`announcement_date` where present (plus the [contract §9](pit-data-contract.md) lag), **not**
from `ex_date`. Where announcement timing is absent, the lag applies and
`public_bound_derivation = DATE_PLUS_LAG` records that the value is a bound, written to
`public_available_upper_bound` and never to the exact field.

**Adjustment rule, distinct from the above.** A corporate action becomes *knowable* at
announcement and *effective* at its ex-date. An adjustment factor may only be applied to bars
on or after the ex-date, and only if the action was admissible at `as_of`. Knowing about a
future split and applying it are two different operations, and only the second is look-ahead.

## 7a. `adjusted_bar_artifact` — `INTERVAL` · **`DERIVED_ARTIFACT`**, not a fact

**New in revision 2**, resolving the contradiction between revision 1's schema and its
implementation plan.

| Field | Type | Notes |
|---|---|---|
| `artifact_id` | string, **PK** | Derived hash of the key below — not generated |
| `adjustment_policy` | enum, **key** | `SPLIT_ONLY` · `SPLIT_AND_DIVIDEND` · `TOTAL_RETURN` |
| `resolved_profile` | enum, **key** | |
| `as_of_epoch` | instant, **key** | The cutoff fixing which actions are admissible |
| `corporate_action_dataset_version` | string, **key** | |
| `raw_bar_dataset_version` | string, **key** | |
| `security_id_scope` | string, **key** | Universe version or explicit id set |
| `information_origin` | enum | `DERIVED_ARTIFACT` |
| `output_validity` | enum | `INTERVAL` |
| `valid_time_start` / `valid_time_end` | date / date | the `INTERVAL` validity fields — the span of sessions this series covers. An adjusted *series* spans sessions, so `INTERVAL` fits it where `SESSION_SCOPED` would have forced one artifact per session |
| `lineage` | list | **complete** — the §6 `price_bar` and §7 `corporate_action` rows consumed, by `dataset_version` and selector |
| `artifact_first_built_time` | instant | **the normative name.** Revision 5 called this `built_at` here and `artifact_first_built_time` everywhere else |
| `derivation_spec_version` | string | the adjustment implementation version |
| `artifact_content_hash` | string | **the normative name.** SHA-256 of the produced series; revision 5 called it `content_hash` here |

**One normative name per field.** `built_at` and `content_hash` are retired from this entity:
they read as substitutes for the required derived-envelope fields while being spelled
differently, which is precisely the drift the documentation audit exists to catch.

**It is a cache, and it must behave like one.** Recomputing from the key must reproduce
`content_hash` bit-identically; a mismatch is a **BLOCKING** quality issue, not a cache miss.
No adjusted series exists anywhere in the system that is not keyed this way.

## 8. `filing` — `RETROSPECTIVE` · `AUTHORITATIVE_PUBLIC`

The provenance anchor for everything fundamental.

| Field | Type | Notes |
|---|---|---|
| `filing_id` | string, **PK** | Accession number or equivalent |
| `security_id` / `entity_id` | FK | |
| `form_type` | string | `10-K` · `10-Q` · `8-K` · `20-F` · `40-F` |
| `period_of_report` | date? | |
| `filing_date` | date | |
| `acceptance_time` | instant | **The authoritative `public_available_time` source** |
| `amends_filing_id` | FK? | Amendments are relationships, not overwrites |
| `document_url` | string | |
| `observation_time` | instant | the `RETROSPECTIVE` anchor — when the document was submitted. The class invariant `acceptance_time >= observation_time` is then a real check: a filing cannot be accepted before it is submitted |
| `«envelope»` | | |

## 9. `fundamental_fact` — `RETROSPECTIVE` · `AUTHORITATIVE_PUBLIC`

**Reported values only.** One fact, one period, one revision. Narrow by design: a wide statement
table cannot express per-line-item restatement.

| Field | Type | Notes |
|---|---|---|
| `security_id` | FK, **PK part** | |
| `fiscal_period` | string, **PK part** | e.g. `2025Q3` |
| `period_type` | enum, **PK part** | `QUARTERLY` · `ANNUAL` |
| `metric` | string, **PK part** | `revenue`, `eps_diluted`, `shares_outstanding`, … |
| `revision_sequence` | int, **PK part** | 0 = as originally reported |
| `value` | decimal | |
| `unit` / `currency` | string | Normalised at ingestion |
| `filing_id` | FK → `filing` | The document that carried this value |
| `revision_chronology_completeness` | enum | `COMPLETE` · `FIRST_AND_LATEST_ONLY` · `UNKNOWN` |
| `observation_time` | instant | the `RETROSPECTIVE` anchor — the end of the fiscal period the value describes. The class invariant then says a reported figure cannot be public before the period it reports on ended |
| `«envelope»` | | source envelope |

**`derivation` is gone from this table**, and its absence is the point. Revision 3 carried
`derivation ∈ {REPORTED, DERIVED_TTM, DERIVED_RATIO}` on a table declared
`AUTHORITATIVE_PUBLIC`, so a trailing-twelve-month figure **we computed** inherited the
authority of a filing. Nobody filed a TTM. Derived values move to §9a.

**Revision views** are governed by the query's `revision_view`
([contract §6](pit-data-contract.md)):

| `revision_view` | Selects |
|---|---|
| `AS_KNOWN_AT_AS_OF` | highest `revision_sequence` whose `decision_available_time <= as_of` |
| `ORIGINAL_FILING_ONLY` | `revision_sequence = 0`, if admissible at `as_of` |
| `LATEST_RESTATED` | highest `revision_sequence`, ignoring `as_of` — **forbidden in research** |

**`revision_chronology_completeness` is the honesty field.** `AS_KNOWN_AT_AS_OF` needs every
intermediate revision. A provider supplying only "as reported" and "most recent reported"
yields `FIRST_AND_LATEST_ONLY`, and any run touching such rows carries
`REVISION_CHRONOLOGY_INCOMPLETE`. Which value a provider supports is a **BLOCKING provider
test** ([implementation-plan.md](implementation-plan.md) §2–§3).

## 9a. `fundamental_derived_fact` — `PERIOD_END` · **`DERIVED_ARTIFACT`**

Trailing-twelve-month aggregates, ratios, margins, growth rates — everything computed from §9
rather than reported.

| Field | Type | Notes |
|---|---|---|
| `security_id` | FK, **PK part** | |
| `fiscal_period` | string, **PK part** | |
| `period_type` | enum, **PK part** | `TTM` · `DERIVED` |
| `metric` | string, **PK part** | `revenue_ttm`, `gross_margin`, `revenue_growth_yoy`, … |
| `value` | decimal | |
| `unit` / `currency` | string | |
| `derivation` | enum | `DERIVED_TTM` · `DERIVED_RATIO` · `DERIVED_GROWTH` |
| `period_end` | date | the `PERIOD_END` validity field |
| `«derived envelope»` | | `lineage` names **every** §9 row consumed, each with its `revision_sequence` |

Two consequences that make the split worth its cost:

- **A TTM is only as available as its slowest constituent quarter.** Under any profile its
  `decision_available_time` is the max over the four quarters it consumed — which is the right
  answer, and one a `REPORTED`-flagged row on the §9 table could not express.
- **`lineage` records the `revision_sequence` of each input.** A TTM built from as-reported
  quarters and one built from restated quarters are different artifacts with different hashes,
  and the manifest can tell them apart.

## 10. `earnings_schedule_announcement` — `ANNOUNCED_FORWARD` · `AUTHORITATIVE_PUBLIC`

**Revision 3's `earnings_event` violated the atomic-fact rule (§0.0)** by packing four facts
with four different availability stories into one row: a date announced weeks ahead, a release
that happened, a consensus the provider computed, and a surprise we calculated. Whichever
timestamps that row carried, three of the four were wrong. It is now five entities sharing an
`event_id` and nothing else.

| Field | Type | Notes |
|---|---|---|
| `event_id` | string, **PK part** | shared across §10–§10d |
| `schedule_revision` | int, **PK part** | scheduled dates change; each change is a row |
| `security_id` | FK | |
| `fiscal_period` | string | |
| `scheduled_date` | date | |
| `expected_session_slot` | enum? | `BEFORE_MARKET` · `AFTER_MARKET` · `UNSPECIFIED` — **as announced**, not derived |
| `announcement_time` | instant | when *this schedule* was announced — the class anchor |
| `«envelope»` | | source envelope |

**Issuer-confirmed dates only.** The company announced a date; that is an `ANNOUNCED_FORWARD`
public fact anchored on `announcement_time`.

## 10a. `earnings_release` — `RETROSPECTIVE` · `AUTHORITATIVE_PUBLIC`

The event that actually happened.

| Field | Type | Notes |
|---|---|---|
| `event_id` | string, **PK** | |
| `security_id` | FK | |
| `fiscal_period` | string | |
| `observation_time` | instant | when the release occurred — the class anchor |
| `announcement_time_confidence` | enum | `VERIFIED` · `FILING_DERIVED` · `DATE_ONLY` · `UNKNOWN` |
| `session_classification` | enum? | `BEFORE_MARKET` · `AFTER_MARKET` · `INTRADAY` — **derived from the timestamp**, never asserted |
| `reported_eps` / `reported_revenue` | decimal? | as released |
| `filing_id` | FK? | the 8-K, where one exists |
| `«envelope»` | | |

## 10b. `earnings_consensus_snapshot` — `SAMPLED_STATE` · **`PROVIDER_DERIVED`**

What consensus stood immediately before the release. A **provider** fact, not a public one.

| Field | Type | Notes |
|---|---|---|
| `event_id` | FK, **PK part** | |
| `metric` | string, **PK part** | `eps`, `revenue` |
| `snapshot_time` | instant, **PK part** | the class anchor |
| `consensus_value` | decimal | |
| `analyst_count` | int | |
| `«envelope»` | | `public_available_time` **null**, `public_time_derivation = NOT_APPLICABLE` |

`snapshot_time` **is** the `SAMPLED_STATE` `sample_time` anchor — one field, named for what the
domain calls it and referenced by the class invariant.

Unpopulated while the estimates gap is open ([provider-evaluation.md](provider-evaluation.md)
§2.8). It exists now so that the §10c artifact has a lineage target to refuse against.

## 10c. `earnings_surprise_artifact` — `EVENT_REFERENCED` · **`DERIVED_ARTIFACT`**

| Field | Type | Notes |
|---|---|---|
| `event_id` | FK, **PK part** | |
| `metric` | string, **PK part** | |
| `surprise_absolute` / `surprise_pct` | decimal | |
| `observation_reference` | FK | the §10a release row this surprise describes — the `EVENT_REFERENCED` validity field |
| `«derived envelope»` | | `lineage` = the §10a release row **and** the §10b consensus row |

**This is the clearest case for the whole derived model.** A surprise is a function of a public
release and a proprietary consensus. Its eligibility is the intersection, so it is
**ineligible under `PUBLIC_PIT`** — the market could not compute this number from public
information alone, because one input was never public.

And it simply does not exist while §10b is unpopulated. Revision 3 handled that with a nullable
`surprise_pct` on a shared row and a rule saying *null, never zero*; the rule was right and the
shape was wrong. **A missing artifact is a stronger statement than a null column**, and it
reaches the required-input check ([contract §13.3](pit-data-contract.md)) instead of quietly
propagating a null into a factor.

## 10d. `guidance_event` — `RETROSPECTIVE` · `AUTHORITATIVE_PUBLIC`

| Field | Type | Notes |
|---|---|---|
| `guidance_id` | string, **PK** | |
| `event_id` | FK? | where guidance accompanied a release |
| `security_id` | FK | |
| `guidance_change` | enum | `RAISED` · `LOWERED` · `MAINTAINED` · `INITIATED` · `WITHDRAWN` |
| `metric` / `period` / `low` / `high` | — | the guided range, where given |
| `observation_time` | instant | when guidance was issued — the class anchor |
| `filing_id` | FK? | |
| `«envelope»` | | |

Guidance is its own fact with its own timing: it is frequently issued on a call **after** the
release it accompanies, and it is sometimes issued with no release at all.

## 10e. `earnings_schedule_estimate` — `SAMPLED_STATE` · **`PROVIDER_DERIVED`**

| Field | Type | Notes |
|---|---|---|
| `event_id` | string, **PK part** | |
| `snapshot_time` | instant, **PK part** | the `SAMPLED_STATE` `sample_time` anchor |
| `security_id` | FK | |
| `fiscal_period` | string | |
| `estimated_date` | date | |
| `expected_session_slot` | enum? | `BEFORE_MARKET` · `AFTER_MARKET` · `UNSPECIFIED` |
| `«envelope»` | | `public_available_time` **null**, `public_time_derivation = NOT_APPLICABLE` |

**Revision 4 gave both of these one entity and one temporal class**, which was wrong twice
over. A vendor's *estimate* of an earnings date is not announced by anyone — it is the vendor's
current opinion, resampled as it changes, so it is `SAMPLED_STATE` and `PROVIDER_DERIVED`. An
issuer's *announcement* is a public event with an announcement instant. They have different
anchors, different origins and different eligibility: the estimate is **ineligible under
`PUBLIC_PIT`**, the announcement is not.

Blueprint §10.2 needs a forward earnings flag either way. Only one of the two is a public fact,
and a backtest that treats a vendor forecast as public knowledge is using information the market
did not have in that form.

## 11. `analyst_estimate_snapshot` — `SAMPLED_STATE` · **`PROVIDER_DERIVED`**

**Schema defined now; not populated while the blocking gap is open.** Defining it costs
nothing and prevents a later retrofit from being the moment PIT discipline gets negotiated.

| Field | Type | Notes |
|---|---|---|
| `security_id` | FK, **PK part** | |
| `estimate_period` | string, **PK part** | `FY1` · `FY2` · `Q1` … |
| `metric` | string, **PK part** | `eps`, `revenue` |
| `snapshot_time` | instant, **PK part** | When this consensus stood — the `SAMPLED_STATE` `sample_time` anchor |
| `consensus_mean` / `median` / `high` / `low` / `stddev` | decimal | |
| `analyst_count` | int | |
| `«envelope»` | | |

**This is the entity revision 2 would have made unusable.** A proprietary consensus has no
authoritative public release instant — `public_available_time` is null with
`public_time_derivation = NOT_APPLICABLE`, and `snapshot_time` is the provider's own. Under
revision 2's universal public-time requirement the row was ineligible everywhere; under
revision 3 it is ineligible under `PUBLIC_PIT` (correctly — the market never saw it) and
eligible under `PROVIDER_REALISTIC_PIT` and `FORWARD_SYSTEM`
([contract §3.2 example B](pit-data-contract.md)).

## 12. `analyst_revision` — `RETROSPECTIVE` · **`PROVIDER_DERIVED`**

| Field | Type | Notes |
|---|---|---|
| `revision_id` | string, **PK** | |
| `security_id` | FK | |
| `broker_id` / `analyst_id` | string? | Where the licence permits |
| `estimate_period` / `metric` | string | |
| `previous_value` / `new_value` | decimal | |
| `revision_time` | instant | **The field the entire domain exists for**, and the `RETROSPECTIVE` `observation_time` anchor: a revision cannot be available before the analyst made it |
| `revision_type` | enum | `ESTIMATE` · `RATING` · `PRICE_TARGET` |
| `«envelope»` | | |

## 13. `borrow_snapshot` — `SAMPLED_STATE` · **origin per row**

**Schema defined now; not populated until Phase 3C qualifies a source.**

| Field | Type | Notes |
|---|---|---|
| `security_id` | FK, **PK part** | |
| `snapshot_time` | instant, **PK part** | |
| `source` | enum, **PK part** | `IBKR` · `ORTEX` · … — **borrow is source-specific, not a market-wide fact** |
| `sample_time` | instant | The instant the state was observed |
| `shortable_quantity` | integer? | |
| `borrow_fee_bps` / `rebate_rate_bps` | decimal? | |
| `is_hard_to_borrow` | bool? | |
| `is_ssr_active` | bool? | Blueprint §12 requires SSR state pre-execution |
| `locate_required` | bool? | |
| `coverage_scope` | enum | `SINGLE_SYMBOL` · `BULK_UNIVERSE` — a per-symbol history cannot support a broad-universe backtest |
| `information_origin` | enum | **per row.** `PROVIDER_DERIVED` where the source stamps the observation with its own time; `SYSTEM_OBSERVED` where we polled a live endpoint that carries no timestamp |
| `«envelope»` | | |

**Which of the two applies to IBKR is a Phase-3C qualification outcome, not an assumption**
([implementation-plan.md](implementation-plan.md) §4.1). It matters: a `SYSTEM_OBSERVED`
borrow series is eligible **only** under `FORWARD_SYSTEM`, which means it cannot support a
historical short backtest at all — only forward validation.

**`source` is part of the primary key deliberately.** IBKR borrow availability and a
market-wide securities-finance aggregate measure different things; merging them would
manufacture a history no venue ever offered.

## 14. `classification_history` — **class and origin per row**

Revision 4 declared this entity `ANNOUNCED_FORWARD` for every row. That is right for an index
provider announcing a reclassification effective next quarter, and wrong for the two other
things this table holds: a vendor's rolling opinion of a company's sector, and a classification
read off a filing. Different facts, different anchors, different origins.

| Field | Type | Notes |
|---|---|---|
| `security_id` | FK, **PK part** | |
| `scheme` | enum, **PK part** | `VENDOR` · `SIC` · `GICS` *(licensed)* |
| `valid_from` | date, **PK part** | |
| `valid_to` | date? | |
| `classification_fact_kind` | enum, **PK part** | `CHANGE_ANNOUNCEMENT` · `PROVIDER_SNAPSHOT` · `FILING_OBSERVED` |
| `announcement_time` | instant? | required for `CHANGE_ANNOUNCEMENT` |
| `sample_time` | instant? | required for `PROVIDER_SNAPSHOT` |
| `observation_time` | instant? | required for `FILING_OBSERVED` |
| `sector` / `industry` / `sub_industry` | string | |
| `temporal_fact_class` | enum | **per row**, per the table below |
| `information_origin` | enum | **per row**, per the table below |
| `«envelope»` | | source envelope |

| `classification_fact_kind` | `temporal_fact_class` | `information_origin` | Anchor |
|---|---|---|---|
| `CHANGE_ANNOUNCEMENT` | `ANNOUNCED_FORWARD` | `AUTHORITATIVE_PUBLIC` when the index provider or exchange announced it publicly; `PROVIDER_DERIVED` for a licensed scheme's private notice | `announcement_time` |
| `PROVIDER_SNAPSHOT` | `SAMPLED_STATE` | `PROVIDER_DERIVED` | `sample_time` |
| `FILING_OBSERVED` | `RETROSPECTIVE` | `AUTHORITATIVE_PUBLIC` | `observation_time` |

`FILING_OBSERVED` is `RETROSPECTIVE` rather than `SAMPLED_STATE` because it models a specific
fact — *this filing stated this classification* — with an instant it was observed at, not a
state we sampled. That distinction decides which invariant applies, which is why the fact kind
is a primary-key part rather than a hint.

## 15. `source_document` — `RETROSPECTIVE` · **origin per row, external documents only**

Provenance for the later AI layer (CLAUDE.md §7). Schema now, population later.

| Field | Type | Notes |
|---|---|---|
| `document_id` | string, **PK** | |
| `security_id` | FK? | |
| `document_type` | enum | `FILING` · `EARNINGS_RELEASE` · `TRANSCRIPT` · `GUIDANCE` · `NEWS` |
| `source_url` | string | |
| `publication_time` | instant | **is the `RETROSPECTIVE` `observation_time` anchor** — the instant the document was published. Named for the domain, referenced by the class invariant, and **not nullable**: a document with no publication instant is not a source document, it is an unresolved acquisition |
| `retrieval_time` | instant | |
| `document_version` | int | Documents get amended |
| `content_hash` | string | SHA-256; detects silent amendment |
| `model_version` / `prompt_version` | string? | **Reserved.** Populated only when agents exist |
| `information_origin` | enum | **per row**, see below |
| `«envelope»` | | |

**Documents do not share one origin, and revision 3 assumed they did.**

| Document | `information_origin` |
|---|---|
| SEC filing, issuer press release | `AUTHORITATIVE_PUBLIC` |
| licensed transcript | `PROVIDER_DERIVED` |
| licensed vendor news | `PROVIDER_DERIVED` |

**Every row here is an external document with a real `source_url` and `publication_time`.**
Revision 4 also listed "internally generated summary → `DERIVED_ARTIFACT`" in this table, which
broke the entity: a summary we generate has no source URL, no publication time and no
`system_first_seen_time`, so it could not satisfy the source envelope this table requires. It
moves to §15a.

This matters more than it looks. When the AI layer arrives, a Research Agent citing a licensed
transcript produces evidence that is **ineligible under `PUBLIC_PIT`** — the market never saw
that transcript in that form. Recording the origin now means the constraint is inherited rather
than rediscovered.

## 15a. `research_summary_artifact` — `EVENT_REFERENCED` · **`DERIVED_ARTIFACT`**

Anything KalpaMani generates *about* source documents: an extraction, a summary, a structured
evidence record. Schema now, population when the AI layer is authorized.

| Field | Type | Notes |
|---|---|---|
| `summary_id` | string, **PK** | |
| `security_id` | FK? | |
| `summary_type` | enum | `EXTRACTION` · `SUMMARY` · `STRUCTURED_EVIDENCE` · `CHALLENGE` |
| `observation_reference` | list | the §15 `source_document` rows this describes — the `EVENT_REFERENCED` validity field |
| `model_version` | string | **required** |
| `prompt_version` | string | **required** |
| `content_hash` | string | |
| `«derived envelope»` | | `lineage` = the §15 rows consumed; **no** `source_url`, `publication_time` or `system_first_seen_time` |

Two properties fall out of the derived envelope, and both are exactly what CLAUDE.md §7
requires of AI output:

- **Availability is the max over the documents it read.** A summary of a licensed transcript is
  no more available than the transcript, and is **ineligible under `PUBLIC_PIT`** because the
  transcript is.
- **`model_version` and `prompt_version` are required, not reserved.** They are part of
  `derivation_spec_version` in substance: change either and the artifact is a different
  artifact with a different hash, which is what makes AI output auditable rather than merely
  logged.

## 16. `ingestion_run`

Makes every curated row traceable to the act that fetched it, and is where
`provider_available_time` evidence originates.

| Field | Type | Notes |
|---|---|---|
| `ingestion_run_id` | string, **PK** | Deterministic where possible, in the ADR-0004 §2 spirit |
| `provider` / `dataset` | string | |
| `started_at` / `completed_at` | instant | |
| `status` | enum | `SUCCESS` · `PARTIAL` · `FAILED` |
| `requested_range` | string | |
| `record_count` / `new_record_count` | int | New-record count is what distinguishes a backfill from an update |
| `is_backfill` | bool | Set by the origin-aware rule in [data-quality-plan.md](data-quality-plan.md) §4.2.4: the run delivered rows whose **valid-time coverage** (`observation_time` / `effective_date` / `sample_time`) extends earlier than the prior run's minimum, **or** whose `source_anchor` predates it. Revision 4 keyed this on `public_available_time` alone, so a backfill of proprietary or system-observed rows — the ones whose timing is least trustworthy — was invisible |
| `bronze_artifact_hashes` | list[string] | SHA-256 of every raw payload written |
| `code_commit_sha` / `config_version` | string | |

## 17. `data_quality_issue`

Quality findings are **data**, not log lines — because a `BLOCKING` issue must be queryable by
the code that refuses to serve a result ([contract §10](pit-data-contract.md) rule 8).

| Field | Type | Notes |
|---|---|---|
| `issue_id` | string, **PK** | |
| `check_name` | string | |
| `severity` | enum | `INFO` · `WARNING` · `BLOCKING` |
| `dataset` / `security_id` / `session_date` | string / FK? / date? | Scope |
| `detected_at` | instant | |
| `ingestion_run_id` | FK | |
| `detail` | string | |
| `status` | enum | `OPEN` · `ACKNOWLEDGED` · `RESOLVED` · `SUPPRESSED` |
| `suppression_reason` / `suppressed_by` | string? | A suppression is a **human act with a name on it** |

## 18. `dataset_version`

The unit of reproducibility.

| Field | Type | Notes |
|---|---|---|
| `dataset_version` | string, **PK** | e.g. `gold/2026.08.26.1` |
| `layer` | enum | `BRONZE` · `SILVER` · `GOLD` |
| `built_at` | instant | |
| `built_from_run_ids` | list[FK] | |
| `code_commit_sha` | string | |
| `resolved_profile` | enum? | Non-null for profile-specific gold artifacts. **Named `resolved_profile`, never the ambiguous `information_set_profile`**: an artifact is built under the profile the run actually resolved to, and a downgraded run produces `PUBLIC_PIT` artifacts ([contract §13.2](pit-data-contract.md)) |
| `universe_definition_version` | string? | |
| `corporate_action_dataset_version` | string? | |
| `adjustment_policy` | enum? | Non-null for adjusted artifacts |
| `lag_policy_version` | string | Which lag table produced the availability times |
| `content_hash` | string | |
| `is_published` | bool | |
| `superseded_by` | FK? | Versions are superseded, **never mutated** |

---

## 19. Cross-cutting invariants

Stated once, enforced by test:

1. **No table has an in-place update path.** Revisions are rows.
2. **No entity is keyed on a ticker.** `ticker_history` is the only table where a ticker
   appears in a key, and it is keyed with time.
3. **Every curated row carries exactly one envelope — SOURCE or DERIVED** (§0.1c), never a
   blend and never neither. A source row without a resolvable availability, or a derived row
   without complete lineage, cannot be served.
4. **`decision_available_time` is never a stored column on a fact row.** It is computed per
   profile at query time.
5. **`public_available_time` is never copied from a vendor field** without passing the
   [contract §5.1](pit-data-contract.md) ladder, even when the two coincide.
6. **`provider_available_time` is never invented by a lag.** Known, or null.
7. **Every entity declares a `temporal_fact_class`.** There is no default class.
7a. **Every row declares an `information_origin`.** There is no default origin, and a row is
    served only under a profile its origin is eligible for (§0.1a).
7c. **One row, one origin, one class, one envelope** (§0.0). Independently changing facts are
    separate rows even when they share an identifier.
7d. **A `DERIVED_ARTIFACT` row carries complete lineage and no source times.** Its availability
    and eligibility are computed from its inputs; it never invents public or provider
    availability.
7e. **An exact time and a conservative bound are never the same field.** A bound is never
    written into `public_available_time` or `provider_available_time`, and where both exist,
    `exact <= bound`.
7f. **Exact and bound derivations have separate vocabularies** (§0.2). No member of an exact
    enum may name a bound field, and no member of a bound enum may name an exact field.
8a. **A derived artifact declares `output_validity` and its required field(s)**, never a source
    `temporal_fact_class`.
8b. **A declared `temporal_fact_class` always has a usable anchor present** —
    `RETROSPECTIVE`/`observation_time`, `ANNOUNCED_FORWARD`/`announcement_time`,
    `SAMPLED_STATE`/`sample_time`. Where the exact instant is unavailable, an explicitly named
    upper-bound field stands in (`announcement_time_upper_bound`); **exactly one of the pair is
    required, never neither.** A nullable anchor with no alternative is not an anchor.
8c. **A source entity never contains a `DERIVED_ARTIFACT` row.** Where a domain has both — raw
    bars and bars we resampled — they are separate entities (§6, §6a).
7b. **`NOT_APPLICABLE` and `UNKNOWN` are never conflated.** The first means the time does not
    exist; the second means it exists and we failed to establish it. One is usable, the other
    is not.
8. **No adjusted series exists outside a keyed `adjusted_bar_artifact`.**
9. **Broker-native identifiers appear nowhere in this schema.** The data platform and the
   brokerage boundary do not meet (ADR-0002 §13, Blueprint §17).
10. **No brokerage account identifier, account-binding digest, or broker order id may enter
    any of these tables** — CLAUDE.md §3, and the reason INC-0002 is open.
