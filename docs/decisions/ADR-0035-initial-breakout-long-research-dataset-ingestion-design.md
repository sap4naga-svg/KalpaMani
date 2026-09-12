# ADR-0035 — Ingestion design for the initial Breakout Long research dataset

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0035 is proposed and carries no authority.
That is a statement about the present, it will remain true of these days after any later merge, and it
is not to be rewritten as though this decision had authority before it was accepted. On merge, this ADR
becomes **ACCEPTED / IN FORCE** as **architecture, contracts and acceptance criteria only**.

**Nothing was run to produce this design.** No AWS CLI or SDK call, no STS, SSO or Secrets Manager
call, no S3 operation, no Terraform command, no provider request, no acquisition, no assessment, no
private-report retrieval, no ingestion, no backtest and no broker activity. Every fact about the provider
below is taken from public documentation already recorded in the provider-source register; nothing is
taken from the private combined report.

**Accepting this ADR authorizes no execution.** It authorizes no ingestion, backfill or update, no
provider request, no credential use, no IAM or Terraform change, no deployment, no read of the licensed
store, no backtest and no Brain implementation. **Design acceptance, infrastructure design, infrastructure
application, the first bounded ingestion, and G2 closure are five separate gates**, and this decision
opens only the first.

**This ADR is proposed on the same pull request as ADR-0034 and depends on it.** Both become effective
together on that pull request's single independently reviewed merge; this ADR cannot be in force without
ADR-0034, and neither is in force before that merge.

---

## 1. Context

### 1.1 The decision this design serves

[ADR-0034](ADR-0034-select-sharadar-for-initial-equity-research-domains.md) — proposed on the same pull
request, on which this ADR depends — records the owner's partial G1 decision: Sharadar `tickers` and `stocks` selected for initial
equity research; `actions` selected with announcement-based signals and spinoff treatment gated; G2 open
with `PROVIDER_REALISTIC_PIT` as the target profile. The first research consumer is the Breakout Long
module of the accepted Strategy Brain specification, whose data needs are daily price bars, a
survivorship-aware historical universe, split-adjusted series, liquidity, and listing lifecycle facts
(`docs/phase4/strategy-brain-specification.md` §5, §17.1, §22).

### 1.2 What already exists, and is reused rather than redesigned

| Layer | Accepted implementation | Reused here as |
|---|---|---|
| point-in-time contract | `docs/phase3/pit-data-contract.md`; `contracts/vocabulary.py`, `resolution.py`, `anchors.py`, `envelope.py` | the four information times, the per-dataset `EXCLUDE` / `BOUND` gap policies, the global `DOWNGRADE`, profile eligibility by origin |
| immutable Bronze | `ingest/bronze.py` (local), `ingest/publication.py` + `storage/s3.py` (licensed S3); ADR-0011, ADR-0019 write-only conditional `PutObject` | the source-snapshot layer: payload bytes stored exactly as received, content-addressed, append-only, three objects per acquisition |
| acquisition mode | `AcquisitionMode` — `QUALIFICATION`, `BACKFILL`, `UPDATE` (ADR-0013) | `BACKFILL` for the initial load, `UPDATE` for increments; declared, never inferred |
| provider adapter | `ingest/sharadar/{datasets,client,transport,bronze,redaction}.py` (ADR-0009) | the request builder, origin-pinned transport, disclosure guard and Bronze bridge — no bulk route, explicit windows, explicit pagination |
| Silver normalisation | `normalize/silver.py` | vendor rows → `security_id`, exchange-calendar session dates, UTC instants with derivation, `revision_sequence` rows |
| curation | `curate/universe.py`, `adjustment.py`, `lineage.py`, `build.py`, `publication.py`, `resolution_run.py` | stored per-session universe membership; adjustment as a pure keyed function; exact lineage; the resolution receipt every Gold build carries |
| quality | `quality/{plan,checks,runner,report}.py`; `docs/phase3/data-quality-plan.md` | a versioned, closed quality plan validated against what ran |
| reproducibility | `contracts/manifest.py`; `pit/query.py`; `docs/phase3/reproducibility-and-provenance.md` | the derived `run_id`, the mandatory `limitations` block, requested-versus-resolved recording |
| principals | ADR-0021/0022 — two qualification actors; ADR-0023/0024/0025 — private bindings | the trust boundary pattern for private artifacts; the qualification actors themselves are **not** reused for production |

### 1.3 What does not exist, and what this design deliberately leaves to later gates

- **No production ingestion runner.** The only acquisition entry points are the qualification ones; they
  refuse `BACKFILL` and `UPDATE` by construction.
- **No research-read surface on the licensed store.** ADR-0011's store has no read; ADR-0018's read is
  scoped to the assessment actor and the qualification prefixes. Silver and Gold cannot be built until a
  research-build principal exists.
- **No production principals.** The acquisition and assessment permission sets are qualification-scoped.
- **No compute.** ADR-0007's ephemeral-task model is provisioned as a foundation and unused.

Each is named in §6 as its own gate. **This ADR designs; it does not close any of them.**

---

## 2. Scope of the initial dataset

```text
provider                      Sharadar (ADR-0034)
tables                        tickers (snapshot) · stocks (daily bars) · actions (corporate actions)
securities                    U.S. common stocks on NYSE, NASDAQ and NYSE American, active and delisted,
                              identified by permaticker; funds, ADR-only and OTC-only listings excluded
history                       provider depth (January 1998 -> T-1) for actions; a bounded initial window for
                              stocks chosen by the owner in the ingestion authorization (see 5.2); a full
                              tickers snapshot per acquisition run
derived artifacts             security master · ticker_history · universe_membership (per session) ·
                              split-adjusted bar artifact (SPLIT_ONLY, forward-normalized) · liquidity
                              measures (ADDV, price floor) · corporate_action facts
profile                       PROVIDER_REALISTIC_PIT target; PUBLIC_PIT ineligible for stocks (ADR-0010)
not in scope                  fundamentals, events, estimates, borrow, options, sector history, intraday
```

---

## 3. Design

### 3.1 Immutable source snapshots — the Bronze layer and the acquisition plan

**Every provider response is stored byte for byte, exactly as received, and never replaced.** The
accepted Bronze contract applies unchanged: payload objects content-addressed by SHA-256, an acquisition
claim and an acquisition record per request, one conditional `PutObject` each, `IfNoneMatch="*"`, SSE-S3,
a full-object SHA-256 sent and verified. A re-fetch that returns different bytes is a **new** artifact;
identical bytes are an idempotent no-op on the payload and a new claim and record. The acquisition
actor is **write-only**: no `HeadObject`, no `GetObject`, no listing (ADR-0019).

**Production Bronze lives under its own prefixes**, never under the qualification prefixes:

```text
licensed/bronze/sharadar/<dataset>/objects/sha256/<digest>          payload bytes
licensed/bronze/sharadar/<dataset>/acquisitions/<date>/<digest>.<run-id>.json
licensed/bronze/_acquisition_claims/...                             the neutral claim namespace
```

**The acquisition plan is deterministic, compiled and bounded — the qualification plan's discipline at
production scale.** Requests are generated in one canonical order (dataset, then window, then page) from
a plan whose ceilings are compiled constants that may be lowered by configuration and never raised:

| Dataset | Request shape | Page limit | Ceiling per run |
|---|---|---|---|
| `tickers` | one full snapshot, paginated; no window (the vendor refuses one) | 10,000 | compiled |
| `actions` | by `date` window, canonical fixed-length windows from 1998-01-01 to `T-1`, paginated | 10,000 | compiled |
| `stocks` | **by session date** — one request per `date`, paginated — so each response is a whole cross-section and the history is versioned session by session | 10,000 | compiled |

A page-two-or-later request is a completeness probe as well as a fetch: a non-empty final page whose
row count equals the limit is `DELIVERY_TRUNCATED` for that window and blocks the affected session.
**No bulk route, no implicit window, no sort parameter, zero automatic provider retries, sequential
issue with at least one second of pacing, a per-response byte ceiling, a per-run byte ceiling, and a
per-run elapsed deadline on an injected monotonic clock** — each already compiled for the qualification
runtime and reused with production values that the ingestion authorization fixes.

**Modes.** The initial load runs as `AcquisitionMode.BACKFILL`; daily increments run as `UPDATE`
requesting `T-1` for `stocks` and a trailing window for `actions` and a fresh `tickers` snapshot. The
mode is declared by the plan, recorded in every acquisition record, and never inferred.

**Multi-run backfill without resumption.** ADR-0018's no-resume rule stands: an execution identity is
single-use and a halted run is never resumed. A backfill larger than one run is a **sequence of runs,
each with its own identity and its own slice of the canonical request list**, cut deterministically by
the plan. The slice boundaries and the completed-slice ledger are an **owner-only private artifact**
under the private root, held to the ADR-0023 trust boundary, written by the runner at run end and read
by the next run's plan — never from S3, because the acquisition actor cannot read. The research-build
actor (§3.9) later reconciles that ledger against the acquisition records it can read; a disagreement is
a BLOCKING finding.

### 3.2 Versioning

Three things are versioned, and they are kept apart:

| Versioned thing | Mechanism | Where it appears |
|---|---|---|
| **source bytes** | payload digest; acquisition record with retrieval instant, request coordinates, `acquisition_mode`, execution identity | Bronze; the Silver row's `source_digest` and `acquisition_id` |
| **source facts** | `revision_sequence` per `(security_id, session_date)` for bars and per action key for actions: a later acquisition delivering different bytes for a row already seen yields a **new revision**, never an overwrite; the vendor's `lastupdated` date is carried as `provider_last_updated_date` on every row | Silver |
| **the transformation** | `source_schema_version` (compiled), the observed schema digest per payload, `universe_rule_version`, `adjustment_policy`, `resolution_policy_version`, the exchange-calendar version, the commit | the manifest and the `run_id` |

**A revision never inherits an earlier version's availability.** Each row *version* — each distinct
byte content for a row key — carries its own provider-availability evidence and its own
`system_first_seen_time`. A later revision starts from the first-seen bound of *its own* acquisition,
whatever the earlier version's timing was; a build that served revision `v2` at a time established only
for `v1` would be serving a fact nobody could have held, and is refused (§3.9, example T-1).

**Schema drift is a finding, not a surprise.** The observed column set and order of every payload is
digested at normalisation; a digest not in the accepted set for that dataset is `SCHEMA_UNSTABLE` and
BLOCKING until the schema is reviewed and the accepted set is versioned.

### 3.3 Availability timestamps

The four information times of the point-in-time contract apply to every Silver row. The rules below are
**the documented availability rules G2 asks for**; they are written so that every row is served under
exactly one derivation and no row is ever served earlier than the evidence supports.

| Axis | `stocks` (bars) | `actions` | `tickers` (snapshot) |
|---|---|---|---|
| `information_origin` | `PROVIDER_DERIVED` (ADR-0010) | `AUTHORITATIVE_PUBLIC` — a split, dividend, listing or delisting is a public fact delivered by a vendor | `PROVIDER_DERIVED` attribute rows; `security` is `DERIVED_ARTIFACT` |
| `temporal_fact_class` | `RETROSPECTIVE`, keyed to the exchange session | `ANNOUNCED_FORWARD` by nature, but with **no announcement anchor delivered** (`PSR-SHD-094/112`) | `SAMPLED_STATE` |
| public time | not applicable — `PUBLIC_PIT` ineligible | exact: unknown. **Bound:** `public_available_upper_bound` = the ex-date session open, `PublicBoundDerivation.DATE_PLUS_LAG` with lag zero — an ex-date fact is public by its ex-date; announcement anchor `AnnouncementBoundDerivation.NONE` | not applicable |
| provider time — **rule P-1 (vendor-date bound)** | a **bound, never an exact instant**: `lastupdated` is a date-only field, so it can at most bound the availability of the row version it describes. `provider_available_upper_bound` = the last instant of the stamped date in the **evidenced** vendor timezone, or — absent timezone evidence — the last instant of that date anywhere on Earth (UTC−12:00), whichever is later; `provider_available_time` stays null. **Three separate prerequisites**, none of which owner acceptance can supply: (i) **field semantics evidence** that `lastupdated` refers to the delivered row *version* and bounds its availability — the public documentation says *last changed*, which upper-bounds the availability of the *current* version only if the stamp is reliable per version; (ii) **timezone evidence**, else the conservative fallback; (iii) **precision recorded as a bound**. The contract has no member for this derivation — `ProviderBoundDerivation` offers `FIRST_SEEN_UPPER_BOUND` and `DELIVERY_WINDOW` only — so P-1 requires the extension **`ProviderBoundDerivation.VENDOR_DATE_UPPER_BOUND`**, proposed here and **gated** until a contract ADR adds it and the evidence exists (criterion G2-A) | same rule, same prerequisites | same rule, same prerequisites |
| provider time — **rule P-2 (bound)** | `DatasetGapPolicy.BOUND`: `provider_available_upper_bound` = the acquisition's retrieval instant, `ProviderBoundDerivation.FIRST_SEEN_UPPER_BOUND`; `provider_available_time` stays null; limitation tokens `PROVIDER_AVAILABILITY_UNKNOWN`, `PROVIDER_TIME_BOUNDED` | same | same |
| provider time — **rule P-3 (delivery-window bound, version-specific)** | `ProviderBoundDerivation.DELIVERY_WINDOW`, and only for a row version with **version-specific evidence** that *these bytes* existed at the claimed time — a dated archival capture containing the identical row, or a per-version vendor record. **A service-inception date and a delivery schedule establish that *some* version of a row was delivered on a date; they do not establish that the version retrieved today is that version**, because the vendor revises rows in place (`lastupdated`, `PSR-SHD-022`). Without version-specific evidence the row falls to P-2. Where the evidence exists, the bound is the second documented daily delivery (23:30 ET) of the evidenced date (criterion G2-D) | same, keyed to the action date, same evidence requirement | not applicable |
| `system_first_seen_time` | the acquisition record's retrieval instant, exact, for every row | same | same |
| governing time under `PROVIDER_REALISTIC_PIT` | `resolved_provider_time` | `max(resolved_public_time, resolved_provider_time)` | `resolved_provider_time` |

**Rule order.** P-3 applies only to a row version with version-specific evidence; otherwise P-1 only
once the contract extension exists and its three prerequisites are met for the dataset; otherwise P-2 —
**first-seen timing is the default, and the only rule that needs no evidence beyond the acquisition
record.** Every rule yields a **bound**; no rule in this design writes an exact `provider_available_time`.
**A row is never served under a later rule's time while labelled with an earlier rule's derivation**,
**a later revision never inherits an earlier version's bound** (§3.2), and the manifest's per-dataset
resolution map records which rule admitted how many rows.

**The consequence that must be stated rather than discovered.** Under P-2 alone, a bar first ingested on
day *D* is admissible under `PROVIDER_REALISTIC_PIT` only from *D*. A backtest over sessions before the
first ingestion admits **nothing** under P-2, because a backfilled row may not become historically
available merely because the session it describes is old (contract §3.4). Historical admissibility
under the target profile therefore rests on P-1 or P-3 — both of which need evidence this repository does
not yet hold, and neither of which an acceptance can manufacture — and that is exactly the split §4 makes
between controls implementable now and evidence requiring additional sources. `DOWNGRADE` to `PUBLIC_PIT` is **not** available for `stocks`, because the
origin is ineligible; a research run that cannot satisfy the target profile is refused, not relabelled.

### 3.4 Historical-universe construction — the survivorship control

Universe membership is **built once per session and stored** (`curate/universe.py`), never filtered from
today's listings.

**The decision cutoff.** Membership for session `d` is fixed at one instant, `decision_time(d)`: the
exchange-calendar open of session `d` minus a compiled operational margin (initial value: thirty minutes;
a rule parameter in the manifest). **Trades during session `d` may occur only in securities that are members
of `membership(d)`**, and `membership(d)` may consume only facts whose resolved availability under the
resolved profile is **≤ `decision_time(d)`**. Session `d`'s own bar does not exist at that instant, so **no
clause may depend on session `d`'s completed bar** — every price, volume and history clause reads bars
through session `d−1` only. Under `PROVIDER_REALISTIC_PIT` this cutoff binds twice: the `d−1` bar must
have been *published* by then, and its **provider-availability bound** (§3.3) must also be ≤
`decision_time(d)` — which, under P-2, no bar acquired after the fact ever is.

**Decision-time eligibility and later completeness are separate questions.** Whether a member actually
traded on `d`, whether its `d` bar arrived, and whether it was delisted during `d` are **completeness and
quality facts** checked afterwards (§3.7); they may mark a session's results incomplete or a fill
unrealistic, and they never rewrite `membership(d)`. A rule that looked at `d`'s bar to decide `d`'s
membership would be the look-ahead this section exists to prevent (§3.9, example C-1).

For the initial dataset the rule, versioned as `universe_rule_version = breakout-long-v1`, admits a
`security_id` on session `d` when every clause holds at `decision_time(d)`:

| Clause | Source, and the revision consumed | Exclusion reason |
|---|---|---|
| **listing life** contains `d`: listed on or before `d−1` and not delisted on or before `d−1` — from `actions` listing/delisting **events** admissible at `decision_time(d)`; the `tickers` `firstpricedate`/`lastpricedate` bounds are a **snapshot attribute** and may serve only from the snapshot revision admissible at `decision_time(d)` | `actions`; `tickers` attribute revision | `HISTORY` |
| **exchange** in {NYSE, NASDAQ, NYSE American} — from the `security_attribute` revision admissible at `decision_time(d)`; **no revision admissible → the clause is indeterminate and the security is excluded** | `tickers` attribute revision | `EXCHANGE`; indeterminate → `ATTRIBUTE_UNAVAILABLE` |
| **security type** is a domestic common stock — same rule, same revision discipline | `tickers` attribute revision | `SECURITY_TYPE`; indeterminate → `ATTRIBUTE_UNAVAILABLE` |
| a bar exists for `d−1` and for at least `N_history` sessions before it, each admissible at `decision_time(d)` | `stocks` | `HISTORY` |
| unadjusted close on `d−1` ≥ the price floor | `stocks` | `PRICE` |
| average daily dollar volume over the trailing window ending `d−1` ≥ the ADDV floor | `stocks` | `ADDV` |

**Every lookback ends at `d−1`, and every input is the revision admissible at `decision_time(d)`.** The
numeric floors, the window lengths and the operational margin are rule parameters carried in the manifest,
not constants a rebuild could silently change. Delisted securities are members while listed and disappear
at delisting — which is what makes the dataset survivorship-aware — and a security that reappears after a
delisting is a distinct listing episode.

**A current snapshot never silently becomes historical truth — for any attribute.** `tickers` is a
`SAMPLED_STATE` snapshot with **no dated history for exchange, security type, listing bounds, sector or
industry** (`PSR-SHD-096`, `PSR-SHD-113`). Every attribute row is admissible only from the revision that
first delivered it, under that revision's own availability bound (§3.3). So for sessions before the first
snapshot's bound, the exchange and security-type clauses are **indeterminate** and the security is excluded
with `ATTRIBUTE_UNAVAILABLE` — a second proposed vocabulary member, implemented only under the ingestion
gate — rather than admitted on the strength of a value observed years later. Sector-relative features are
excluded from the initial dataset for the same reason. **Only additional sources can change this for the
past**: event-dated listing and exchange facts (the `actions` listing events, where they carry them; exchange
master files; index or listing archives) are what would make an attribute clause determinable for a
historical session (criterion G2-H). Listing lifecycle events are exactly as complete as the vendor's
`actions` table, and a security whose events and snapshot bounds disagree is a quality finding (§3.7).

### 3.5 Identifier changes

- **`security_id` is a deterministic function of `permaticker`**, namespaced by provider; it is never
  derived from `ticker`, and a lookup by symbol without a session date is refused.
- **`ticker_history`** is built from `actions` ticker-change events, closed by the current symbol from
  the `tickers` snapshot; each row is `(security_id, symbol, valid_from, valid_to)` with the vendor's
  reuse rule honoured — a reused symbol belongs to the active company and the delisted company carries
  the numeric suffix (`PSR-SHD-117`).
- **The `stocks` table carries no `permaticker`**, and the vendor keys history to the *current* symbol
  ("rewired", `PSR-SHD-117`). Silver therefore maps each `stocks` row to `security_id` through the
  `tickers` snapshot **acquired in the same run**, and the mapping must be one-to-one for every symbol
  present — a symbol with zero or two `permaticker`s in that snapshot is BLOCKING for that symbol's rows.
- A later snapshot that maps a symbol differently produces a **new `security_attribute` revision**, never
  a rewrite of earlier Silver rows; the affected `stocks` rows are re-resolved under the new revision at
  the next build and the change is a WARNING finding with counts.

### 3.6 Corporate-action handling

| Action | Handling in the initial dataset |
|---|---|
| split, reverse split | a `corporate_action` fact keyed to the ex-date; the **only** input to the adjusted-bar artifact under `AdjustmentPolicy.SPLIT_ONLY`, `AdjustmentConvention.FORWARD_BASE_NORMALIZED` — factors applied to bars **on or after** the ex-date (schema 7; `curate/adjustment.py`), so history already cited is never rewritten |
| cash dividend, special dividend | recorded as facts; **not applied** — the Breakout Long entry template is price-level based and dividend adjustment is a separate policy a later decision may enable |
| listing, delisting, delist reason, ticker change | consumed by §3.4 and §3.5 |
| **spinoff** | recorded as a fact; **never adjusted for**; every security with a spinoff ex-date inside the dataset window is flagged, and its adjusted-bar artifact and every artifact depending on it is **excluded from the session of the first spinoff ex-date onward** until a later decision resolves the vendor's spinoff semantics. This requires one vocabulary addition — `UniverseExclusionReason.UNRESOLVED_CORPORATE_ACTION` — proposed here and implemented under the ingestion gate, not silently |
| merger, acquisition counterparty, rights, ADR ratio change, other | recorded as facts, not consumed |
| **announcement-based use of any action** | **GATED** (ADR-0034 §2.2): no announcement anchor exists; no feature, filter or signal may depend on when an action became known |

**The vendor's own adjusted closes are evidence, not inputs.** `closeadj` and the split-adjusted OHLC
columns are stored in Silver and compared against the repository's `SPLIT_ONLY` reconstruction as a
quality check (§3.7); they are never used as the adjusted series.

### 3.7 Quality checks — the initial plan

The quality plan is a closed, versioned list (`quality/plan.py`); `checks_run` and `checks_not_run`
together must equal it exactly. Plan `breakout-long-ingest-v1` names these check families, each with the
severity the data-quality plan assigns:

| Family | Checks | Severity |
|---|---|---|
| structural | payload decodes as strict UTF-8 CSV; observed schema digest in the accepted set; no duplicate `(ticker, date)` in a cross-section; no duplicate action key | BLOCKING |
| completeness | final page not at the limit (`DELIVERY_TRUNCATED`); every planned request has a record; per-session row count within the expected band from the prior session | BLOCKING / WARNING |
| temporal envelope | session date on the exchange calendar; no session after `T-1`; every row carries exactly one provider-time derivation, and it is a **bound**; the ordering invariant `resolved_public ≤ resolved_provider ≤ system_first_seen` where applicable; no row served under a rule not admitted for its dataset; **no revision served under an earlier version's bound**; **no membership clause reads session `d`'s bar** | BLOCKING |
| market data | `low ≤ open, close ≤ high`; non-negative volume; zero-volume run length; close-to-close jumps beyond a threshold without a split on the ex-date; missing sessions per security against the calendar | WARNING → BLOCKING by rule |
| identity | one `permaticker` per symbol in the same-run snapshot; bars outside `[firstpricedate, lastpricedate]`; ticker-change events consistent with `ticker_history`; delisting event date versus last bar | BLOCKING / WARNING |
| adjustment reconciliation | repository `SPLIT_ONLY` reconstruction versus the vendor's split-adjusted columns within tolerance; any security with a spinoff flagged `UNRESOLVED_CORPORATE_ACTION` | WARNING / BLOCKING |
| history-admissibility census | per dataset and calendar year: rows admissible under P-3, P-1 and P-2, rows excluded, and — **for every attribute the universe rule consumes: exchange, security type, listing bounds, sector, industry** — the count of securities per session-year whose attribute revision is admissible at `decision_time(d)` versus `ATTRIBUTE_UNAVAILABLE`; and the per-year count of sessions whose `membership(d)` is determinable at all — an INFO report that feeds the owner's G2 decision and stays inside the licensed store | INFO |
| cross-provider | none available; every manifest carries `SINGLE_SOURCE_UNVERIFIED` | — |

A BLOCKING finding refuses Gold publication for the affected scope; a WARNING is recorded in the report
and the manifest; no check may be loosened without a plan version change.

### 3.8 Reproducibility

- **Every Gold dataset carries a resolution receipt** (`curate/build.py`) and **every research result a
  manifest** whose derived `run_id` covers: the set of Bronze acquisition digests consumed; the Silver
  normalisation version and accepted schema digests; `universe_rule_version` and its parameters;
  `adjustment_policy` and convention; the per-dataset resolution map and `resolution_policy_version`;
  the resolved profile; `as_of`; the exchange-calendar version; the commit.
- **Lineage is exact** (`curate/lineage.py`): a membership row names the listing revision, attribute row
  and bars it consumed.
- **Rebuild criterion**: two builds from the same Bronze acquisition set, on the same commit, produce
  byte-identical Gold and identical `run_id`; a differing rebuild is a defect, never a refresh.
- **Every manifest declares its limitations** with positive evidence: `SINGLE_SOURCE_UNVERIFIED` always;
  `PROVIDER_AVAILABILITY_UNKNOWN` and `PROVIDER_TIME_BOUNDED` whenever P-2 admitted rows;
  `ORIGIN_INELIGIBLE_ROWS_EXCLUDED` where relevant.
- **Retention and licensing**: Bronze, Silver, Gold and every artifact from which vendor rows could be
  reconstructed are LICENSED, live only in the deletion-first licensed store, and stay inside the
  cloud-deletion runbook's 30-day obligation. Manifests carry no vendor rows.

### 3.9 Adversarial acceptance examples

**These are fixtures the ingestion gate must build and the quality plan must fail or pass as stated.** They
are acceptance examples for future runtime code; **a governance test that checks this document's wording
proves nothing about runtime correctness**, and none of these fixtures exists yet.

| # | Fixture | Must |
|---|---|---|
| **T-1** timing revision | row key `(security S, session 2019-03-05)` acquired as version `v1` on 2026-10-01 (first-seen bound `b1`), then re-delivered as `v2` with different bytes on 2026-11-15 (bound `b2 > b1`). A build with `as_of` between `b1` and `b2` requests the row | serve `v1` only; a build that serves `v2` under `b1` is **refused** (`REFUSED` at manifest emission, not annotated); the manifest records one revision admitted, one excluded by time |
| **T-2** delivery-window without version evidence | the same `v2`, plus a documented vendor delivery schedule covering 2019-03-05 but no capture of `v2`'s bytes on that date | P-3 is **not** applied; `v2` carries `FIRST_SEEN_UPPER_BOUND` = `b2`; a fixture that assigns a `DELIVERY_WINDOW` bound to `v2` **fails** |
| **T-3** delivery-window with version evidence | `v2` plus a dated archival capture whose row bytes are identical to `v2`, dated 2019-03-06 | P-3 applies with the evidenced date; the manifest cites the evidence digest; the bound is a bound, and `provider_available_time` stays null |
| **D-1** date precision | a row with `lastupdated = 2019-03-06`, no timezone evidence, and the `VENDOR_DATE_UPPER_BOUND` extension present | `provider_available_upper_bound` = 2019-03-06T23:59:59.999 at UTC−12:00 (2019-03-07T11:59:59.999Z); `provider_available_time` **null**; a fixture that writes an exact instant from the date **fails** |
| **D-2** date precision, timezone evidenced | the same row with evidenced vendor timezone America/New_York | bound = 2019-03-07T04:59:59.999Z; still a bound; the derivation names the evidence |
| **D-3** date precision, extension absent | the same row, but the contract has no `VENDOR_DATE_UPPER_BOUND` member | P-1 is unavailable; the row falls to P-2; a fixture that emits any vendor-date bound **fails** |
| **C-1** decision cutoff | security `S` satisfies every clause on bars through `d−1` but its `d` bar is absent (halted on `d`) | `S ∈ membership(d)`; the missing `d` bar is a completeness finding, not an exclusion; a rule that excludes `S` from `membership(d)` because of `d`'s bar **fails** |
| **C-2** decision cutoff, availability | `S`'s `d−1` bar has a provider-availability bound later than `decision_time(d)` (e.g. first seen the following week) | `S ∉ membership(d)` with reason `HISTORY`; a fixture that admits it **fails** |
| **C-3** decision cutoff, delisting during `d` | `S ∈ membership(d)` and an `actions` delisting event dated `d` | membership unchanged; the delisting is a completeness finding for `d` and an exclusion from `membership(d+1)` |
| **A-1** historical attribute | the only `tickers` snapshot was first seen in 2026; the build asks for `membership(2019-03-05)` | the exchange and security-type clauses are indeterminate; every security is excluded with `ATTRIBUTE_UNAVAILABLE`; the census reports zero attribute-determinable securities for 2019; a fixture that admits `S` on the 2026 snapshot's exchange value **fails** |
| **A-2** historical attribute with an event-dated source | as A-1, plus an additional event-dated exchange-listing source admissible in 2019 | the clause resolves from that source; the manifest names it; `SINGLE_SOURCE_UNVERIFIED` is replaced for that attribute by the cross-source check's outcome |
| **V-1** revision inheritance across rules | `v1` admitted under P-3 with 2019 evidence; `v2` arrives with no evidence | `v2` is P-2 only; the resolution map shows the per-version split; a fixture in which `v2` inherits `v1`'s P-3 bound **fails** |

### 3.10 The infrastructure boundary — designed here, decided later

Production needs two principals the qualification package does not have, and neither is created by this
ADR:

| Principal | May | May not |
|---|---|---|
| **production acquisition actor** | one governed secret retrieval; conditional `PutObject` under the production Bronze prefixes and the claim namespace | any `GetObject`, `HeadObject`, listing, delete, copy, CONTROL, qualification prefixes |
| **research-build actor** | exact `GetObject` on production Bronze; `PutObject` of Silver and Gold under licensed prefixes; read of its own Silver/Gold; publication of manifests to CONTROL **only once CONTROL is undeferred** | any provider or credential access; delete; listing beyond its own build outputs; the qualification prefixes |

Compute is ADR-0007's ephemeral task model inside the private account; **no vendor row leaves the private
boundary**, and no laptop copy of Silver or Gold is part of the design. Permission sets, assignments,
Terraform and deployment are each their own gate.

---

## 4. Acceptance criteria for closing G2

G2 asks which information-set profile governs results that inform capital. The target is
`PROVIDER_REALISTIC_PIT` (ADR-0034 §2.3). It may be closed when the owner records, in a further ADR,
that the following hold. **Each criterion says whether it can be satisfied with controls this repository
can implement now, or needs historical evidence from an additional source.**

| # | Criterion | Implementable now | Needs additional sources |
|---|---|---|---|
| **G2-A** | **Rule P-1 evidenced, not merely accepted**: (i) field-semantics evidence that `lastupdated` bounds the availability of the delivered row *version*; (ii) timezone evidence or the recorded conservative fallback; (iii) the `VENDOR_DATE_UPPER_BOUND` contract extension accepted by its own ADR, so precision is recorded as a bound; and the owner's written record of which evidence was reviewed | the gate, the bound arithmetic and the fallback are implementable now; the extension is a contract ADR | the semantics and timezone evidence must come from the private cross-run evidence and/or vendor documentation or correspondence; **owner acceptance cannot manufacture it** |
| **G2-H** | **Historical attribute admissibility understood**: the census reports, per session-year, how many securities have an admissible exchange, security-type and listing-bound revision at `decision_time(d)`, and the owner records whether the resulting universe horizon is acceptable or whether event-dated attribute sources are to be obtained | the census and the `ATTRIBUTE_UNAVAILABLE` exclusion are implementable now (the exclusion member is a vocabulary addition under the ingestion gate) | event-dated exchange, security-type and listing evidence for historical sessions needs additional sources |
| **G2-B** | **Forward availability from first ingestion**: every row carries an exact `system_first_seen_time`, and P-2 produces a sound `FIRST_SEEN_UPPER_BOUND` for every row from the first production run onward | **yes** — entirely a repository control | none |
| **G2-C** | **Per-dataset resolution map in every manifest**, entering `run_id`, with exact / bounded / excluded counts and the rule that admitted each row | **yes** — the manifest contract already carries the map | none |
| **G2-D** | **Delivery-window bound (rule P-3) established per row version**: version-specific evidence that the retrieved bytes existed at the claimed time — dated archival captures or per-version vendor records — for the rows it is applied to; a service-inception date and a delivery schedule are necessary context and are **not sufficient** | the rule, its version-evidence requirement and the fall-through to P-2 are implementable now | **yes** — the archival captures or per-version records do not exist in this repository and would come from an additional source; without them P-3 admits nothing |
| **G2-E** | **History-admissibility census reviewed**: the owner has seen, per year, how many rows each rule admits, and accepts the resulting research horizon | the census (§3.7) is implementable now; it needs the research-build actor to run | the *horizon* it reveals may motivate additional sources; that is the owner's call |
| **G2-F** | **No profile mixing possible**: a run that cannot be served under `PROVIDER_REALISTIC_PIT` is refused, never downgraded, for `PROVIDER_DERIVED` datasets | **yes** — a manifest-emission refusal | none |
| **G2-G** | **Corporate-action timing bounded honestly**: actions carry the ex-date public bound and no announcement anchor; announcement-based use stays gated until an announcement source exists | the bound and the gate are implementable now | an announcement-dated source (e.g. an exchange notice feed or EDGAR-derived events, Phase 3B) would be needed to lift the gate |

**G2 closes only by a written owner ADR that cites which criteria are met by controls and which by
evidence, and names the accepted research horizon.** Meeting G2-B, G2-C, G2-F and G2-G alone yields a
provider-realistic dataset whose admissible history begins at the first production ingestion; extending
that history backwards is exactly what G2-A or G2-D must supply, and G2-H bounds what a historical
universe can even be determined for. **No criterion is satisfied by the merge of this ADR.**

---

## 5. Acceptance criteria for authorizing the first bounded ingestion

### 5.1 Controls that must exist and pass offline before any authorization

| # | Criterion |
|---|---|
| **I-1** | A production acquisition plan module with compiled ceilings (requests per run, bytes per response and per run, elapsed deadline, pacing, page limits, zero provider retries), refusing any limit above its constant; synthetic tests prove the canonical order, the slice cut, and that a plan issues zero requests when refused |
| **I-2** | A production runner that declares `BACKFILL`/`UPDATE`, publishes through the write-only surface only, keeps the owner-only slice ledger under the ADR-0023 trust boundary, refuses resumption of a spent identity, and prints only allowlisted sentences and integer counts |
| **I-3** | Silver normalisation for the three tables implementing §3.3 rules P-2 (default), P-3 (version-evidence gated) and P-1 (extension gated), per-version availability with no inheritance across revisions, §3.4's `decision_time(d)` cutoff, §3.5 identity mapping and §3.6 action handling, with the `UNRESOLVED_CORPORATE_ACTION` and `ATTRIBUTE_UNAVAILABLE` vocabulary additions |
| **I-4** | Quality plan `breakout-long-ingest-v1` with every check in §3.7 implemented, plus the adversarial fixtures of §3.9 (T-1…T-3, D-1…D-3, C-1…C-3, A-1, A-2, V-1) and the earlier ones (a truncated page, a duplicate symbol mapping, a bar before listing, a served row without a derivation), each failing or passing exactly as stated |
| **I-5** | The rebuild criterion of §3.8 proven on synthetic Bronze: byte-identical Gold and identical `run_id` across two builds |
| **I-6** | Static guards: the production acquisition path imports no read surface; the research-build path imports no credential or transport; no vendor row can reach a log, manifest or public output |
| **I-7** | `pytest`, `ruff check`, `ruff format --check`, `mypy`, the docs audit and the integrity audit all pass at the reviewed commit |

### 5.2 Decisions and evidence the owner must supply in the ingestion authorization

| # | Item |
|---|---|
| **I-8** | The bounded window for `stocks` in the first backfill (proposal: 2018-01-01 → `T-1`), the request ceiling per run and the number of runs, and the calendar of execution identities |
| **I-9** | The rule parameters of §3.4 (`N_history`, price floor, ADDV floor and window) as the initial values of `breakout-long-v1` |
| **I-10** | Written confirmation that a production subscription is in force for the run dates (owner-side; not recorded here), and that no qualification identity, prefix or binding is reused |
| **I-11** | The infrastructure gates crossed: the two principals of §3.9 designed, reviewed, applied and independently verified; governed profiles materialized; a production runtime binding materialized under the ADR-0023 pattern |
| **I-12** | The written authorization itself, naming one run at a time — a completed run is not permission for the next |

### 5.3 What the first ingestion may not do

No qualification prefix is written; no CONTROL object is written while CONTROL is deferred; no read by
the acquisition actor; no bulk route; no fundamentals, events or estimates table; no announcement-based
feature; no spinoff adjustment; no backtest until Gold exists, a quality report has passed, and a
research authorization is given; no Brain implementation; no broker activity.

---

## 6. Consequences

- **The repository gains a reviewable target for the production data plane** that reuses every accepted
  contract and proposes two `UniverseExclusionReason` members, one `ProviderBoundDerivation` member and one
  private artifact kind (the slice ledger) — each implemented only under its own later gate.
- **The honest research horizon becomes a measured quantity.** The history-admissibility census turns
  "how far back can a provider-realistic backtest go" from an assumption into a number the owner reviews
  before closing G2.
- **The gated uses in ADR-0034 are enforced by construction**: no announcement anchor exists to consume,
  and spinoff-affected securities are excluded rather than adjusted.
- **Five gates follow this one, each its own authorization**: infrastructure design (principals,
  Terraform); infrastructure application; offline implementation of I-1 … I-7 (with the contract
  extension ADR for `VENDOR_DATE_UPPER_BOUND` if P-1 is to exist at all); the first bounded ingestion
  (I-8 … I-12); and G2 closure (G2-A … G2-H). Backtesting, Brain implementation and any capital decision
  sit behind all of them.
- **Phase 3 stays NOT COMPLETE.** This ADR advances Stage 3A's design; 3B, 3C and 3D are untouched.

---

## 7. Rejected alternatives

- **Use the vendor's bulk download route.** Rejected: the accepted client refuses bulk routes by name; a
  table-wide download cannot be paged, bounded or versioned session by session, and its request
  accounting would be a single opaque transfer.
- **Fetch `stocks` per security rather than per session.** Rejected: per-session cross-sections version
  the history by the unit a backtest consumes, make truncation detection per session, and make the
  universe rebuildable from the same slices; per-security pulls would need the symbol list first and
  would re-key the dataset on the vendor's rewired symbols.
- **Resume a halted backfill under the same identity.** Rejected: ADR-0018's no-resume rule exists
  because a resumed identity cannot say which retrieval instant its records carry; a sequence of
  single-use runs over a deterministic slice cut preserves that.
- **Adopt `lastupdated` as an exact `provider_available_time`, with or without an owner acceptance.**
  Rejected: a date-only field cannot yield an instant; the public documentation says *last changed*
  (`PSR-SHD-022/093`), which is the trap the contract §5.2 names; and an acceptance is not evidence. At most
  it is a bound, and the contract must be extended before even that is expressible.
- **Let a vendor delivery schedule date every historical row.** Rejected: a schedule dates deliveries, not
  the version of a row retrieved years later from a vendor that revises rows in place; version-specific
  evidence or first-seen timing, nothing in between.
- **Decide `membership(d)` after session `d`, using `d`'s bar.** Rejected: that is look-ahead by
  construction; membership is fixed at `decision_time(d)` and completeness is checked afterwards.
- **Apply today's exchange, type and listing attributes to historical sessions.** Rejected: a current
  snapshot is not historical truth; an indeterminate clause excludes, and additional sources are the only
  way to make it determinable for the past.
- **Downgrade to `PUBLIC_PIT` when provider timing is unknown.** Rejected on eligibility: the bars are
  `PROVIDER_DERIVED`; a downgraded run would serve ineligible rows.
- **Apply dividend or spinoff adjustment in the initial dataset.** Rejected: the entry template does not
  need total return, and the spinoff semantics are undocumented; adjusting on an undocumented field would
  be a silent assumption inside every adjusted series.
- **Derive the historical universe by filtering today's `tickers`.** Rejected: that is the survivorship
  defect `curate/universe.py` exists to prevent.
- **Reuse the qualification principals and prefixes for production.** Rejected: the qualification
  package's accounting, prefixes and identities are closed and audited; production needs its own
  principals and its own accounting.

---

## 8. Status of everything else

```text
this ADR:                                     PROPOSED / NO AUTHORITY WHILE ITS PR IS OPEN
G1 (tickers, stocks; actions restricted):     DECIDED IN ADR-0034 — in force only on the shared merge
this ADR:                                     DEPENDENT ON ADR-0034 — effective together, on one merge
G2:                                           OPEN — criteria G2-A … G2-H above
production acquisition plan / runner:         NOT IMPLEMENTED / NOT AUTHORIZED
Silver / Gold for the selected domains:       NOT IMPLEMENTED / NOT AUTHORIZED
production principals, Terraform, deployment: NOT DESIGNED IN DETAIL / NOT AUTHORIZED
research-read surface:                        NONE
first bounded ingestion:                      NOT AUTHORIZED / NOT RUN
vocabulary additions (UNRESOLVED_CORPORATE_ACTION,
    ATTRIBUTE_UNAVAILABLE, VENDOR_DATE_UPPER_BOUND):  PROPOSED — implemented only under later gates
backtesting:                                  NOT STARTED
Brain implementation:                         NOT AUTHORIZED
Run A / Run B / combined assessment:          COMPLETED — command outcomes; no retry authorized
P1-P9:                                        IN THE PRIVATE REPORT — NOT RECORDED IN THIS REPOSITORY
Phase 3:                                      NOT COMPLETE
CONTROL:                                      DEFERRED
live trading:                                 HARD-DISABLED
```

**This ADR supersedes no earlier decision and amends no earlier ADR document.** It applies the accepted
point-in-time contract, the accepted Bronze, Silver, curation, quality and manifest implementations, and
the accepted principal and binding patterns to the domains ADR-0034 selects, and it states the criteria
under which the two gates behind it may be opened.
