# Phase 3 — Conceptual Schemas / Data Contracts

**Status: PROPOSED — planning only. Nothing is implemented.**

These are **vendor-neutral data contracts**, not DDL and not a vendor mapping. Per the task
constraint, they are deliberately not overfitted to any provider before the provider decision
is made ([provider-evaluation.md](provider-evaluation.md) §4 is a *proposal*, not a purchase).

Types are conceptual: `instant` is a timezone-aware UTC timestamp; `date` is a calendar date
with no time component and is never silently promoted to an instant
([pit-data-contract.md](pit-data-contract.md) §5.7).

---

## 0. The common envelope

Every curated entity carries the same temporal and provenance envelope. It is written once
here and referenced as **`«envelope»`** rather than repeated eighteen times.

| Field | Type | Meaning |
|---|---|---|
| `source_available_time` | instant | **The governing PIT field.** Derived per contract §4. |
| `source_publish_time` | instant? | As asserted by the source. Nullable. Never queried directly. |
| `ingestion_time` | instant | When we received it. Never a substitute for availability. |
| `valid_from` / `valid_to` | instant / instant? | Interval this version is current for. `valid_to` null = current. |
| `revision_sequence` | int | 0 = original. Monotonic per logical fact. |
| `source_id` | string | Originating document/feed record identity. |
| `vendor_record_id` | string? | Vendor row identity. Carried, never branched on (ADR-0002 §4). |
| `provider` | string | Which vendor supplied this row. |
| `dataset_version` | string | The curated build this row belongs to. |
| `quality_status` | enum | `OK` · `SUSPECT` · `QUARANTINED` |
| `availability_derivation` | enum | Which contract §4 rule produced `source_available_time`: `EXACT` · `VENDOR_TZ` · `DATE_PLUS_LAG` · `SESSION_DERIVED` · `UNKNOWN` |
| `applied_lag` | duration? | Non-null only when `DATE_PLUS_LAG` — surfaced in the research manifest. |

Two envelope rules are load-bearing:

- **`availability_derivation = UNKNOWN` may never participate in a point-in-time query**
  (contract §7 rule 3). The field exists so that the refusal is mechanical rather than a
  matter of judgement.
- **`quality_status = QUARANTINED` rows are excluded from every research query.** They are
  retained, not deleted — deleting the evidence of a data problem is how the same problem
  recurs.

---

## 1. `security`

The permanent identity. Everything joins here.

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

## 2. `listing`

A security relationship with a venue, over time. Separate from `security` because a security
can move venue without becoming a different company.

| Field | Type | Notes |
|---|---|---|
| `listing_id` | string, **PK** | |
| `security_id` | FK → `security` | |
| `exchange` | enum | `NYSE` · `NASDAQ` · `NYSE_AMERICAN` · `OTC` · … |
| `listing_start` / `listing_end` | date / date? | |
| `delisting_reason` | enum? | `MERGER` · `ACQUISITION` · `BANKRUPTCY` · `DEFICIENCY` · `VOLUNTARY` · `UNKNOWN` |
| `successor_security_id` | FK? | For M&A continuity |
| `«envelope»` | | |

## 3. `ticker_history`

The mapping that is wrong most often.

| Field | Type | Notes |
|---|---|---|
| `security_id` | FK → `security` | |
| `ticker` | string | |
| `valid_from` / `valid_to` | date / date? | **PK is (`ticker`, `valid_from`)** — tickers are recycled |
| `change_reason` | enum? | `RENAME` · `MERGER` · `REVERSE_SPLIT` · `EXCHANGE_MOVE` |
| `«envelope»` | | |

**Invariant.** For any (`ticker`, `date`) there is at most one `security_id`. Overlap is a
`BLOCKING` quality issue — an overlap means every join on that ticker is ambiguous.

## 4. `universe_membership`

The survivorship control. **Stored per session, never recomputed at query time.**

| Field | Type | Notes |
|---|---|---|
| `session_date` | date, **PK part** | From `market_session` |
| `security_id` | FK, **PK part** | |
| `universe_definition_version` | string, **PK part** | Changing the rule creates a version |
| `is_member` | bool | |
| `price_at_eval` / `market_cap_at_eval` / `addv_at_eval` | decimal | The values that produced the decision |
| `history_sessions_at_eval` | int | |
| `exclusion_reason` | enum? | `PRICE` · `MARKET_CAP` · `ADDV` · `HISTORY` · `EXCHANGE` · `SECURITY_TYPE` |
| `«envelope»` | | |

**The stored evaluation inputs are not redundant.** They are what makes a membership decision
auditable years later, and what lets a quality check confirm the rule was applied to
admissible data rather than to current data.

## 5. `market_session`

| Field | Type | Notes |
|---|---|---|
| `exchange` | enum, **PK part** | |
| `session_date` | date, **PK part** | The canonical session key |
| `regular_open` / `regular_close` | instant | UTC; **derived from the calendar**, never assumed |
| `extended_open` / `extended_close` | instant | |
| `is_half_day` | bool | ADR-0004 §14 exists because this was once assumed away |
| `is_holiday` | bool | |
| `«envelope»` | | |

## 6. `price_bar`

| Field | Type | Notes |
|---|---|---|
| `security_id` | FK, **PK part** | |
| `session_date` | date, **PK part** | |
| `resolution` | enum, **PK part** | `DAILY` · `MINUTE` |
| `open` / `high` / `low` / `close` | decimal | **Unadjusted.** The traded prices. |
| `volume` | integer | |
| `trade_count` | integer? | |
| `vwap` | decimal? | Where licensed |
| `is_stale` / `had_halt` | bool | A non-trading day is not a zero |
| `«envelope»` | | |

**Adjusted prices are not stored.** They are computed at query time from `price_bar` plus
`corporate_action` rows admissible at `as_of`. Storing an adjusted series would freeze one
adjustment epoch into the data and is precisely defect class 4.

## 7. `corporate_action`

| Field | Type | Notes |
|---|---|---|
| `action_id` | string, **PK** | |
| `security_id` | FK | |
| `action_type` | enum | `SPLIT` · `REVERSE_SPLIT` · `DIVIDEND` · `SPECIAL_DIVIDEND` · `SPINOFF` · `MERGER` · `RIGHTS` · `SYMBOL_CHANGE` · `DELISTING` |
| `announcement_date` | date? | **The PIT-critical field.** Nullable, and its absence is itself information |
| `ex_date` / `record_date` / `pay_date` / `effective_date` | date? | |
| `ratio` / `cash_amount` | decimal? | |
| `«envelope»` | | |

**Availability rule.** `source_available_time` derives from `announcement_date` where present
(plus the contract §6 lag), **not** from `ex_date`. Where `announcement_date` is null, the lag
applies and `availability_derivation = DATE_PLUS_LAG` records that the value is approximate.

## 8. `filing`

The provenance anchor for everything fundamental.

| Field | Type | Notes |
|---|---|---|
| `filing_id` | string, **PK** | Accession number or equivalent |
| `security_id` / `entity_id` | FK | |
| `form_type` | string | `10-K` · `10-Q` · `8-K` · `20-F` · `40-F` |
| `period_of_report` | date? | |
| `filing_date` | date | |
| `acceptance_time` | instant | **The authoritative availability instant** |
| `amends_filing_id` | FK? | Amendments are relationships, not overwrites |
| `document_url` | string | |
| `«envelope»` | | |

## 9. `fundamental_fact`

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
| `is_as_reported` | bool | `true` for `revision_sequence = 0` |
| `filing_id` | FK → `filing` | The document that carried this value |
| `derivation` | enum | `REPORTED` · `DERIVED_TTM` · `DERIVED_RATIO` |
| `«envelope»` | | |

**Research default.** The highest `revision_sequence` **admissible at `as_of`** — which for a
date before any restatement is the original. Restated values are reachable only by asking for
them explicitly.

## 10. `earnings_event`

| Field | Type | Notes |
|---|---|---|
| `event_id` | string, **PK** | |
| `security_id` | FK | |
| `fiscal_period` | string | |
| `scheduled_date` | date? | Forward-looking; supports the "no carry through earnings" rule |
| `announcement_time` | instant? | **Null when unverified** — never guessed |
| `announcement_time_confidence` | enum | `VERIFIED` · `FILING_DERIVED` · `DATE_ONLY` · `UNKNOWN` |
| `session_classification` | enum? | `BEFORE_MARKET` · `AFTER_MARKET` · `INTRADAY` — **derived**, never asserted |
| `reported_eps` / `reported_revenue` | decimal? | |
| `consensus_eps_at_announcement` | decimal? | **Requires `analyst_estimate_snapshot`; null while that gap is open** |
| `surprise_pct` | decimal? | Null when consensus is null. **Never imputed.** |
| `guidance_change` | enum? | `RAISED` · `LOWERED` · `MAINTAINED` · `INITIATED` · `WITHDRAWN` · `NONE` |
| `filing_id` | FK? | |
| `«envelope»` | | |

**`surprise_pct` is null, not zero, when consensus is unavailable.** A zero surprise is a
claim about the world; a null is a statement that we do not know. Conflating them would let
the estimates gap enter the factor pipeline silently, which is the whole thing
[data-domain-inventory.md](data-domain-inventory.md) §H is trying to prevent.

## 11. `analyst_estimate_snapshot`

**Schema defined now; not populated while the blocking gap is open.** Defining it costs
nothing and prevents a later retrofit from being the moment PIT discipline is negotiated.

| Field | Type | Notes |
|---|---|---|
| `security_id` | FK, **PK part** | |
| `estimate_period` | string, **PK part** | `FY1` · `FY2` · `Q1` … |
| `metric` | string, **PK part** | `eps`, `revenue` |
| `snapshot_time` | instant, **PK part** | When this consensus stood |
| `consensus_mean` / `median` / `high` / `low` / `stddev` | decimal | |
| `analyst_count` | int | |
| `«envelope»` | | |

## 12. `analyst_revision`

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

## 13. `borrow_snapshot`

**Schema defined now; not populated until Phase 3C qualifies a source.**

| Field | Type | Notes |
|---|---|---|
| `security_id` | FK, **PK part** | |
| `snapshot_time` | instant, **PK part** | |
| `source` | enum, **PK part** | `IBKR` · `ORTEX` · … — **borrow is source-specific, not a market-wide fact** |
| `shortable_quantity` | integer? | |
| `borrow_fee_bps` | decimal? | |
| `rebate_rate_bps` | decimal? | |
| `is_hard_to_borrow` | bool? | |
| `is_ssr_active` | bool? | Blueprint §12 requires SSR state pre-execution |
| `locate_required` | bool? | |
| `«envelope»` | | |

**`source` is part of the primary key deliberately.** IBKR borrow availability and a
market-wide securities-finance aggregate are different measurements of different things, and
merging them into one series would manufacture a history that no venue ever offered.

## 14. `classification_history`

| Field | Type | Notes |
|---|---|---|
| `security_id` | FK, **PK part** | |
| `scheme` | enum, **PK part** | `VENDOR` · `SIC` · `GICS` *(licensed)* |
| `valid_from` | date, **PK part** | |
| `valid_to` | date? | |
| `sector` / `industry` / `sub_industry` | string | |
| `«envelope»` | | |

## 15. `source_document`

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

Makes every curated row traceable to the act that fetched it.

| Field | Type | Notes |
|---|---|---|
| `ingestion_run_id` | string, **PK** | Deterministic where possible, in the ADR-0004 §2 spirit |
| `provider` / `dataset` | string | |
| `started_at` / `completed_at` | instant | |
| `status` | enum | `SUCCESS` · `PARTIAL` · `FAILED` |
| `requested_range` | string | |
| `record_count` | int | |
| `bronze_artifact_hashes` | list[string] | SHA-256 of every raw payload written |
| `code_commit_sha` | string | |
| `config_version` | string | |
| `«envelope»` | | |

## 17. `data_quality_issue`

Quality findings are **data**, not log lines — because a `BLOCKING` issue has to be
queryable by the code that refuses to serve a result (contract §7 rule 5).

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
| `universe_definition_version` | string? | |
| `corporate_action_version` | string? | |
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
3. **Every curated row carries `«envelope»`.** A row without an availability derivation
   cannot be served.
4. **`source_available_time` is never copied from `source_publish_time`** — it is always
   derived through the contract §4 ladder, even when the two coincide.
5. **Broker-native identifiers appear nowhere in this schema.** The data platform and the
   brokerage boundary do not meet (ADR-0002 §13, Blueprint §17).
6. **No brokerage account identifier, account-binding digest, or broker order id may enter
   any of these tables** — CLAUDE.md §3, and the reason INC-0002 is open.
