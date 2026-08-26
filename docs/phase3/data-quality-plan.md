# Phase 3 — Data Quality and Reconciliation Plan

**Status: PROPOSED — planning only. No check is implemented.**

---

## 1. Principle

Data-quality checks in a trading system are not hygiene. They are the mechanism by which a
result is allowed to be *believed*. The posture is inherited directly from
[ADR-0004](../decisions/ADR-0004-deterministic-order-identity-idempotency-and-execution-lifecycle.md)
§5, which established that missing or corrupt durable state **fails closed** rather than
being read as "nothing happened":

> **A `BLOCKING` data-quality issue open against a dataset makes every research, scanner and
> backtest result that touches it invalid. The result is refused, not annotated.**

Checks are **deterministic**. Given the same inputs they produce the same findings — no
sampling, no thresholds tuned by eye, no model deciding what looks wrong. Findings are stored
as `data_quality_issue` rows ([conceptual-schema.md](conceptual-schema.md) §17), so the code
that refuses to serve a result can query them.

## 2. Severity

| Severity | Meaning | Effect |
|---|---|---|
| **INFO** | Observed, expected, recorded for audit. | none |
| **WARNING** | Anomalous. A human should look. Results stay valid but are **labelled**. | annotation on the research manifest |
| **BLOCKING** | The data cannot support a decision. | **every dependent result is refused** |

Two rules keep severity honest:

- **Escalation by accumulation.** A `WARNING` check firing on more than a configured fraction
  of a dataset becomes `BLOCKING` for that dataset. One bad bar is an anomaly; ten thousand
  is a broken pipeline wearing an anomaly costume.
- **Suppression is a named human act.** `data_quality_issue.status = SUPPRESSED` requires
  `suppressed_by` and `suppression_reason`. There is no bulk suppression and no automatic
  ageing-out. INC-0001 lesson applies: *"the automated path has guardrails; the manual path
  had none."*

## 3. Structural checks

| # | Check | Severity |
|---|---|---|
| 3.1 | **Duplicate records** — more than one row for a primary key at the same `revision_sequence` | **BLOCKING** |
| 3.2 | **Schema drift** — vendor payload columns/types differ from the recorded contract | **BLOCKING** |
| 3.3 | **Checksum change** — a bronze artifact hash differs from the one an `ingestion_run` recorded | **BLOCKING** |
| 3.4 | **Unrecognised schema version** in any curated table | **BLOCKING** |
| 3.5 | **Missing envelope** — any curated row with `availability_derivation = UNKNOWN` | **BLOCKING** for PIT queries |
| 3.6 | **Orphan reference** — a foreign key with no target | **BLOCKING** |
| 3.7 | **Stale ingestion** — the newest row for a live-facing dataset is older than its freshness bound | **BLOCKING** for live, **WARNING** for research |

## 4. Temporal and point-in-time checks

These are the checks that exist specifically to catch look-ahead. They are the reason this
document exists.

| # | Check | Severity |
|---|---|---|
| 4.1 | **Revision arriving before publication** — `revision_sequence > 0` with `source_available_time` earlier than the row it revises | **BLOCKING** |
| 4.2 | **Availability before observation** — `source_available_time < observation_time` | **BLOCKING** |
| 4.3 | **Availability after ingestion by more than the latency budget** — data we appear to have had before it existed | **BLOCKING** |
| 4.4 | **Estimate snapshots moving backward in time** — a snapshot series whose `snapshot_time` is non-monotonic | **BLOCKING** |
| 4.5 | **Earnings timestamp inconsistent with the session** — an announcement claimed intraday that falls outside the exchange session, or on a non-session date without weekend/holiday justification | **WARNING**, escalating |
| 4.6 | **Borrow snapshot older than the permitted freshness** for the date it is used at | **BLOCKING** |
| 4.7 | **Corporate action available before its announcement date** | **BLOCKING** |
| 4.8 | **Future-dated availability** — `source_available_time` after the dataset build time | **BLOCKING** |
| 4.9 | **DST-ambiguous instant stored without resolution** | **BLOCKING** |
| 4.10 | **Session-date/UTC-date mismatch** — a bar whose session date was derived by truncating a UTC timestamp rather than from the calendar | **BLOCKING** |

Check 4.1 is worth dwelling on. A restatement whose availability time precedes the original
filing is not merely wrong — it is a row that, if served, hands a backtest the corrected
number before the company published the original one. It is look-ahead in its purest form and
it arrives looking like an ordinary ingestion.

## 5. Market-data checks

| # | Check | Severity |
|---|---|---|
| 5.1 | **Impossible OHLC** — `high < low`, `open` or `close` outside `[low, high]` | **BLOCKING** |
| 5.2 | **Negative or zero price**, negative volume | **BLOCKING** |
| 5.3 | **Missing session** — a calendar session with no bar for a security listed and untraded-halted that day | **WARNING**, escalating |
| 5.4 | **Missing bar within a listed range** for a security in the universe that date | **WARNING**, escalating |
| 5.5 | **Split discontinuity** — a close-to-close move beyond a configured bound with no `corporate_action` explaining it | **BLOCKING** |
| 5.6 | **Adjusted/unadjusted mismatch** — recomputing adjusted from raw + actions does not reproduce the vendor adjusted series within tolerance | **BLOCKING** |
| 5.7 | **Zero volume on a regular session** for a liquid universe member | **WARNING** |
| 5.8 | **Price outside a plausible band** relative to a rolling window | **WARNING** |

Check 5.5 is the one that catches unrecorded corporate actions — the failure that silently
destroys momentum factors, because an unadjusted split looks exactly like a −50% return.

## 6. Identity and universe checks

| # | Check | Severity |
|---|---|---|
| 6.1 | **Ticker-history overlap** — one ticker mapping to two securities on one date | **BLOCKING** |
| 6.2 | **Ticker gap** — a listed security with no ticker for a date inside its listing range | **BLOCKING** |
| 6.3 | **Survivorship leakage** — a universe snapshot whose members are all still listed today, beyond a statistically implausible rate for the era | **BLOCKING** |
| 6.4 | **Delisted-absence** — no delisted securities appear in any historical universe snapshot | **BLOCKING** |
| 6.5 | **Universe recomputation drift** — rebuilding a historical snapshot from the same inputs and rule version yields different membership | **BLOCKING** |
| 6.6 | **Eligibility computed from inadmissible data** — any evaluation input whose `source_available_time` exceeds the snapshot date | **BLOCKING** |
| 6.7 | **Security-type leakage** — non-common-stock in a common-stock universe | **BLOCKING** |

Checks 6.3 and 6.4 are deliberately crude, and that is the point: they are the smoke alarm
for the defect that is otherwise invisible. If a 2012 universe snapshot contains no company
that has since disappeared, the data is not historical, whatever the vendor calls it.

## 7. Cross-provider reconciliation

The reason [provider-evaluation.md](provider-evaluation.md) §4 pairs every primary source
with a cross-check.

| # | Check | Severity |
|---|---|---|
| 7.1 | **Price disagreement** between primary and cross-check beyond tolerance | **WARNING**, escalating |
| 7.2 | **Security-master disagreement** — a delisting, ticker change or listing date present in one master and absent from the other | **WARNING**, escalating to **BLOCKING** on systematic divergence |
| 7.3 | **Corporate-action disagreement** — a split ratio or ex-date differing between sources | **BLOCKING** |
| 7.4 | **Calendar disagreement** between LEAN market hours and `exchange_calendars` | **BLOCKING** |
| 7.5 | **Fundamental disagreement** — Sharadar `ARQ` vs SEC EDGAR XBRL for the same metric, period and filing | **WARNING**, escalating |
| 7.6 | **Conflicting publication timestamps** between sources | **WARNING**; the later time is used (contract §5.6) |

Rule for all of §7: **disagreement is never resolved by silently preferring one source.**
Either a documented precedence rule applies (and is recorded in the manifest), or the row is
quarantined. Two sources that disagree are two claims, and picking the convenient one is how
a data platform starts lying quietly.

## 8. Gating

```
BLOCKING issue OPEN against dataset D
        |
        v
any research / scanner / backtest query touching D
        |
        v
REFUSED  -- not "returned with a warning", not "returned empty"
```

Concretely:

- The PIT query layer consults open `BLOCKING` issues before serving, and raises.
- A backtest cannot start if any input dataset has one open.
- A research manifest **cannot be produced** for a run whose datasets have one open — so a
  result that would be invalid also cannot be made to look reproducible.
- Scanner output produced while a `BLOCKING` issue is open is not presented as valid.

This mirrors the Phase-2 preflight, which exits non-zero and stops a deployment before a
container starts rather than warning inside one.

## 9. Reporting

- Every ingestion run emits a quality report: checks executed, findings by severity, and the
  datasets now gated.
- **Silent truncation is forbidden.** If a check samples, bounds, or skips anything, the
  report says what it skipped. A check that quietly covered less than it claims is worse than
  no check, because it converts an unknown into a false assurance.
- Reports contain **no** brokerage identifiers, account-binding digests or credentials
  (CLAUDE.md §3). The data platform has no reason to know they exist.
