# Phase 3 — Conceptual Schemas / Data Contracts

**Status: PROPOSED — planning only. Nothing is implemented.**

These are **vendor-neutral data contracts**, not DDL and not a vendor mapping. Per the task
constraint, they are deliberately not overfitted to any provider before the provider decision
is made ([provider-evaluation.md](provider-evaluation.md) is a *proposal*, not a purchase).

Types are conceptual: `instant` is a timezone-aware UTC timestamp; `date` is a calendar date
with no time component and is never silently promoted to an instant
([pit-data-contract.md](pit-data-contract.md) §12.6).

> **Revision 2 (2026-08-26).** The envelope no longer carries a single
> `source_available_time`. It carries the four distinct information times from
> [contract §2.1](pit-data-contract.md), and the governing `decision_available_time` is
> **computed per profile, never stored on a fact row**. Every entity now declares a
> `temporal_fact_class`. Adjusted bars are resolved as a keyed cache artifact (§7a).

---

## 0. The common envelope

Written once here, referenced as **`«envelope»`** rather than repeated twenty times.

### 0.1 Information times

| Field | Type | Meaning |
|---|---|---|
| `public_available_time` | instant? | When the fact first became publicly obtainable from the authoritative source. Derived per [contract §5.1](pit-data-contract.md). **Nullable** — and null means "not point-in-time under any profile". |
| `provider_available_time` | instant? | When the selected provider first offered this record. Derived per [contract §5.2](pit-data-contract.md). **Nullable, and its absence is information** ([contract §3.2](pit-data-contract.md)). |
| `system_first_seen_time` | instant | When KalpaMani first held this record. Never null, never estimated. |
| `ingestion_time` | instant | When *this row* was written. A rebuild writes a new row without changing `system_first_seen_time`. |

**`decision_available_time` is not a column.** It is computed at query time from the active
`information_set_profile` ([contract §3](pit-data-contract.md)). Storing it would bake one
profile into the data and is precisely the conflation revision 1 committed.

### 0.2 Temporal classification

| Field | Type | Meaning |
|---|---|---|
| `temporal_fact_class` | enum | `RETROSPECTIVE` · `ANNOUNCED_FORWARD` · `SAMPLED_STATE` — selects which timing invariant applies ([contract §7](pit-data-contract.md)). Declared per entity, not per row, except where noted. |
| `availability_derivation` | enum | Which [contract §5.1](pit-data-contract.md) rule produced `public_available_time`: `EXACT` · `VENDOR_TZ` · `DATE_PLUS_LAG` · `SESSION_DERIVED` · `UNKNOWN` |
| `provider_availability_derivation` | enum | `VENDOR_STAMPED` · `FILE_DROP` · `FIRST_SEEN_UPPER_BOUND` · `UNKNOWN` |
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

- **`availability_derivation = UNKNOWN` may never participate in a point-in-time query**
  ([contract §10](pit-data-contract.md) rule 6). The field exists so the refusal is mechanical
  rather than a matter of judgement.
- **`provider_availability_derivation = UNKNOWN` under `PROVIDER_REALISTIC_PIT`** triggers the
  dataset's declared `EXCLUDE` or `DECLARE` resolution — never a silent fallback.
- **`quality_status = QUARANTINED` rows are excluded from every research query.** Retained,
  not deleted — deleting the evidence of a data problem is how the same problem recurs.
- **The ordering `public <= provider <= system_first_seen` is an asserted invariant**, not an
  assumption. Violations are graded in [data-quality-plan.md](data-quality-plan.md) §4.

---

## 1. `security` — `RETROSPECTIVE`

| Field | Type | Notes |
|---|---|---|
| `security_id` | string, **PK** | Internal, permanent, opaque. **Never a ticker.** |
| `security_type` | enum | `COMMON_STOCK` · `ADR` · `ETF` · `PREFERRED` · `WARRANT` · `UNIT` · `OTHER` |
| `is_common_stock_eligible` | bool | Blueprint §4 admits common stock |
| `country_of_incorporation` | string? | |
| `figi` | string? | Openly licensed; preferred external id |
| `cusip` / `isin` | string? | **Licence-gated**; optional; never the join key |
| `first_listing_date` / `last_listing_date` | date / date? | |
| `«envelope»` | | |

## 2. `listing` — `RETROSPECTIVE`

| Field | Type | Notes |
|---|---|---|
| `listing_id` | string, **PK** | |
| `security_id` | FK → `security` | |
| `exchange` | enum | `NYSE` · `NASDAQ` · `NYSE_AMERICAN` · `OTC` · … |
| `listing_start` / `listing_end` | date / date? | |
| `delisting_reason` | enum? | `MERGER` · `ACQUISITION` · `BANKRUPTCY` · `DEFICIENCY` · `VOLUNTARY` · `UNKNOWN` |
| `successor_security_id` | FK? | M&A continuity |
| `«envelope»` | | |

**Class note.** A delisting is usually `ANNOUNCED_FORWARD` at the row level — exchanges
announce them ahead of the effective date. Where an announcement is captured, the row carries
`temporal_fact_class = ANNOUNCED_FORWARD` and an `announcement_time`; where only the effective
date is known, it is `RETROSPECTIVE` with the §9 lag. This is the one entity whose class is
per-row.

## 3. `ticker_history` — `RETROSPECTIVE`

| Field | Type | Notes |
|---|---|---|
| `security_id` | FK → `security` | |
| `ticker` | string | |
| `valid_from` / `valid_to` | date / date? | **PK is (`ticker`, `valid_from`)** — tickers are recycled |
| `change_reason` | enum? | `RENAME` · `MERGER` · `REVERSE_SPLIT` · `EXCHANGE_MOVE` |
| `«envelope»` | | |

**Invariant.** For any (`ticker`, `date`) there is at most one `security_id`. Overlap is
`BLOCKING` — an overlap means every join on that ticker is ambiguous.

## 4. `universe_membership` — `RETROSPECTIVE`

The survivorship control. **Stored per session, never recomputed at query time.**

| Field | Type | Notes |
|---|---|---|
| `session_date` | date, **PK part** | From `market_session` |
| `security_id` | FK, **PK part** | |
| `universe_definition_version` | string, **PK part** | Changing the rule creates a version |
| `information_set_profile` | enum, **PK part** | **New in revision 2.** Eligibility is evaluated on admissible data, so membership is profile-specific |
| `is_member` | bool | |
| `price_at_eval` / `market_cap_at_eval` / `addv_at_eval` | decimal | The values that produced the decision |
| `history_sessions_at_eval` | int | |
| `exclusion_reason` | enum? | `PRICE` · `MARKET_CAP` · `ADDV` · `HISTORY` · `EXCHANGE` · `SECURITY_TYPE` |
| `«envelope»` | | |

The stored evaluation inputs are not redundant. They make a membership decision auditable
years later, and let a quality check confirm the rule was applied to admissible data rather
than to current data.

## 5. `market_session` — `ANNOUNCED_FORWARD`

Exchange calendars are published in advance. A 2027 holiday schedule known in 2026 is a
correct, non-leaking fact — which is exactly why the blanket rule from revision 1 was wrong.

| Field | Type | Notes |
|---|---|---|
| `exchange` | enum, **PK part** | |
| `session_date` | date, **PK part** | The canonical session key |
| `regular_open` / `regular_close` | instant | UTC; **derived from the calendar**, never assumed |
| `extended_open` / `extended_close` | instant | |
| `is_half_day` / `is_holiday` | bool | ADR-0004 §14 exists because this was once assumed away |
| `announcement_time` | instant? | When the calendar revision publishing this session was released |
| `«envelope»` | | |

## 6. `price_bar` — `RETROSPECTIVE`

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
| `«envelope»` | | |

**Only raw bars are facts.** Adjusted series are computed ([contract §8](pit-data-contract.md))
and, if materialised, live in `adjusted_bar_artifact` below — never here, and never as an
extra column.

## 7. `corporate_action` — `ANNOUNCED_FORWARD`

| Field | Type | Notes |
|---|---|---|
| `action_id` | string, **PK** | |
| `security_id` | FK | |
| `action_type` | enum | `SPLIT` · `REVERSE_SPLIT` · `DIVIDEND` · `SPECIAL_DIVIDEND` · `SPINOFF` · `MERGER` · `RIGHTS` · `SYMBOL_CHANGE` · `DELISTING` |
| `announcement_date` | date? | Nullable; its absence is itself information |
| `announcement_time` | instant? | The timing invariant anchor for this class |
| `ex_date` / `record_date` / `pay_date` / `effective_date` | date? | **May be far later than availability. That is correct, not a violation.** |
| `ratio` / `cash_amount` | decimal? | |
| `«envelope»` | | |

**Availability rule.** `public_available_time` derives from `announcement_time`/
`announcement_date` where present (plus the [contract §9](pit-data-contract.md) lag), **not**
from `ex_date`. Where announcement timing is absent, the lag applies and
`availability_derivation = DATE_PLUS_LAG` records that the value is approximate.

**Adjustment rule, distinct from the above.** A corporate action becomes *knowable* at
announcement and *effective* at its ex-date. An adjustment factor may only be applied to bars
on or after the ex-date, and only if the action was admissible at `as_of`. Knowing about a
future split and applying it are two different operations, and only the second is look-ahead.

## 7a. `adjusted_bar_artifact` — derived cache, not a fact

**New in revision 2**, resolving the contradiction between revision 1's schema and its
implementation plan.

| Field | Type | Notes |
|---|---|---|
| `artifact_id` | string, **PK** | Derived hash of the key below — not generated |
| `adjustment_policy` | enum, **key** | `SPLIT_ONLY` · `SPLIT_AND_DIVIDEND` · `TOTAL_RETURN` |
| `information_set_profile` | enum, **key** | |
| `as_of_epoch` | instant, **key** | The cutoff fixing which actions are admissible |
| `corporate_action_dataset_version` | string, **key** | |
| `raw_bar_dataset_version` | string, **key** | |
| `security_id_scope` | string, **key** | Universe version or explicit id set |
| `content_hash` | string | SHA-256 of the produced series |
| `built_at` | instant | |

**It is a cache, and it must behave like one.** Recomputing from the key must reproduce
`content_hash` bit-identically; a mismatch is a **BLOCKING** quality issue, not a cache miss.
No adjusted series exists anywhere in the system that is not keyed this way.

## 8. `filing` — `RETROSPECTIVE`

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
| `«envelope»` | | |

## 9. `fundamental_fact` — `RETROSPECTIVE`

One fact, one period, one revision. Narrow by design: a wide statement table cannot express
per-line-item restatement.

| Field | Type | Notes |
|---|---|---|
| `security_id` | FK, **PK part** | |
| `fiscal_period` | string, **PK part** | e.g. `2025Q3` |
| `period_type` | enum, **PK part** | `QUARTERLY` · `ANNUAL` · `TTM` |
| `metric` | string, **PK part** | `revenue`, `eps_diluted`, `shares_outstanding`, … |
| `revision_sequence` | int, **PK part** | 0 = as originally reported |
| `value` | decimal | |
| `unit` / `currency` | string | Normalised at ingestion |
| `filing_id` | FK → `filing` | The document that carried this value |
| `derivation` | enum | `REPORTED` · `DERIVED_TTM` · `DERIVED_RATIO` |
| `revision_chronology_completeness` | enum | `COMPLETE` · `FIRST_AND_LATEST_ONLY` · `UNKNOWN` — **see below** |
| `«envelope»` | | |

**Revision views, not a default.** Selection is governed by the query's `revision_view`
([contract §6](pit-data-contract.md)):

| `revision_view` | Selects |
|---|---|
| `AS_KNOWN_AT_AS_OF` | highest `revision_sequence` whose `decision_available_time <= as_of` |
| `ORIGINAL_FILING_ONLY` | `revision_sequence = 0`, if admissible at `as_of` |
| `LATEST_RESTATED` | highest `revision_sequence`, ignoring `as_of` — **forbidden in research** |

**`revision_chronology_completeness` is the honesty field.** `AS_KNOWN_AT_AS_OF` needs every
intermediate revision to be correct. A provider supplying only "as reported" and "most recent
reported" yields `FIRST_AND_LATEST_ONLY`, and any run touching such rows carries
`REVISION_CHRONOLOGY_INCOMPLETE`. Which value a provider actually supports is a **BLOCKING
provider test**, not an assumption ([implementation-plan.md](implementation-plan.md) §2–§3).

## 10. `earnings_event` — `ANNOUNCED_FORWARD`

A scheduled earnings date is announced weeks ahead of the event. Under revision 1's blanket
rule this correct row would have been blocked.

| Field | Type | Notes |
|---|---|---|
| `event_id` | string, **PK** | |
| `security_id` | FK | |
| `fiscal_period` | string | |
| `scheduled_date` | date? | Announced ahead; supports Blueprint §10.2 event-risk flags |
| `schedule_announcement_time` | instant? | Availability anchor for the *scheduled* fact |
| `announcement_time` | instant? | Of the actual release. **Null when unverified — never guessed** |
| `announcement_time_confidence` | enum | `VERIFIED` · `FILING_DERIVED` · `DATE_ONLY` · `UNKNOWN` |
| `session_classification` | enum? | `BEFORE_MARKET` · `AFTER_MARKET` · `INTRADAY` — **derived**, never asserted |
| `reported_eps` / `reported_revenue` | decimal? | |
| `consensus_eps_at_announcement` | decimal? | **Requires §11; null while that gap is open** |
| `surprise_pct` | decimal? | Null when consensus is null. **Never imputed** |
| `guidance_change` | enum? | `RAISED` · `LOWERED` · `MAINTAINED` · `INITIATED` · `WITHDRAWN` · `NONE` |
| `filing_id` | FK? | |
| `«envelope»` | | |

**A scheduled date and an actual release are two facts with two availability times**, which is
why both anchors exist. The scheduled date is `ANNOUNCED_FORWARD`; the realised release is
`RETROSPECTIVE` and is carried on the same row because they share an identity.

**`surprise_pct` is null, not zero, when consensus is unavailable.** A zero surprise is a
claim about the world; a null says we do not know. Conflating them lets the estimates gap
enter the factor pipeline silently.

## 11. `analyst_estimate_snapshot` — `SAMPLED_STATE`

**Schema defined now; not populated while the blocking gap is open.** Defining it costs
nothing and prevents a later retrofit from being the moment PIT discipline gets negotiated.

| Field | Type | Notes |
|---|---|---|
| `security_id` | FK, **PK part** | |
| `estimate_period` | string, **PK part** | `FY1` · `FY2` · `Q1` … |
| `metric` | string, **PK part** | `eps`, `revenue` |
| `snapshot_time` | instant, **PK part** | When this consensus stood |
| `consensus_mean` / `median` / `high` / `low` / `stddev` | decimal | |
| `analyst_count` | int | |
| `«envelope»` | | |

## 12. `analyst_revision` — `RETROSPECTIVE`

| Field | Type | Notes |
|---|---|---|
| `revision_id` | string, **PK** | |
| `security_id` | FK | |
| `broker_id` / `analyst_id` | string? | Where the licence permits |
| `estimate_period` / `metric` | string | |
| `previous_value` / `new_value` | decimal | |
| `revision_time` | instant | **The field the entire domain exists for** |
| `revision_type` | enum | `ESTIMATE` · `RATING` · `PRICE_TARGET` |
| `«envelope»` | | |

## 13. `borrow_snapshot` — `SAMPLED_STATE`

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
| `«envelope»` | | |

**`source` is part of the primary key deliberately.** IBKR borrow availability and a
market-wide securities-finance aggregate measure different things; merging them would
manufacture a history no venue ever offered.

## 14. `classification_history` — `ANNOUNCED_FORWARD`

Index and classification changes are announced before they take effect.

| Field | Type | Notes |
|---|---|---|
| `security_id` | FK, **PK part** | |
| `scheme` | enum, **PK part** | `VENDOR` · `SIC` · `GICS` *(licensed)* |
| `valid_from` | date, **PK part** | |
| `valid_to` | date? | |
| `announcement_time` | instant? | |
| `sector` / `industry` / `sub_industry` | string | |
| `«envelope»` | | |

## 15. `source_document` — `RETROSPECTIVE`

Provenance for the later AI layer (CLAUDE.md §7). Schema now, population later.

| Field | Type | Notes |
|---|---|---|
| `document_id` | string, **PK** | |
| `security_id` | FK? | |
| `document_type` | enum | `FILING` · `EARNINGS_RELEASE` · `TRANSCRIPT` · `GUIDANCE` · `NEWS` |
| `source_url` | string | |
| `publication_time` | instant | |
| `retrieval_time` | instant | |
| `document_version` | int | Documents get amended |
| `content_hash` | string | SHA-256; detects silent amendment |
| `model_version` / `prompt_version` | string? | **Reserved.** Populated only when agents exist |
| `«envelope»` | | |

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
| `is_backfill` | bool | Set when the run delivered records whose `public_available_time` predates the previous run |
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
| `information_set_profile` | enum? | Non-null for profile-specific gold artifacts |
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
3. **Every curated row carries `«envelope»`.** A row without an availability derivation cannot
   be served.
4. **`decision_available_time` is never a stored column on a fact row.** It is computed per
   profile at query time.
5. **`public_available_time` is never copied from a vendor field** without passing the
   [contract §5.1](pit-data-contract.md) ladder, even when the two coincide.
6. **`provider_available_time` is never invented by a lag.** Known, or null.
7. **Every entity declares a `temporal_fact_class`.** There is no default class.
8. **No adjusted series exists outside a keyed `adjusted_bar_artifact`.**
9. **Broker-native identifiers appear nowhere in this schema.** The data platform and the
   brokerage boundary do not meet (ADR-0002 §13, Blueprint §17).
10. **No brokerage account identifier, account-binding digest, or broker order id may enter
    any of these tables** — CLAUDE.md §3, and the reason INC-0002 is open.
