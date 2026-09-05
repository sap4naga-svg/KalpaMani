# Cockpit read-model and API contracts

**Status: ACCEPTED SPECIFICATION EFFECTIVE ON MERGE OF PR #71, and PROPOSED until that merge —
NOT IMPLEMENTED, NOT AUTHORIZED.**

This document specifies the envelopes, read models, endpoint catalog, query semantics and metric
definitions the Cockpit consumes. It is written to be **implementation-reviewable**: a later cycle
should be able to build against it and a reviewer should be able to tell whether the build matches.

**Every schema block in this document is illustrative shape, not runtime code.** No file here is
importable, no type here exists, and **no module under `src/` is created by this document**.

**Introduced by** [ADR-0027](../decisions/ADR-0027-cockpit-and-feedback-architecture-and-governance.md).
**Architecture:** [`COCKPIT_FEEDBACK_EXTENSION.md`](../architecture/COCKPIT_FEEDBACK_EXTENSION.md).

---

## 1. The boundary this document implements

```text
KalpaMani subsystems
    -> immutable facts, events and versioned results     (owned by their subsystems)
        -> dedicated projections and read models          (this document)
            -> versioned read API                         (this document)
                -> Cockpit UI
```

**A read model is built from recorded facts, never by asking a live source.** No read model, no
projection and no endpoint may hold a provider credential, a brokerage credential or an AWS secret,
open a provider session, or contact a broker. **An API proxy must not become a disguised provider or
broker integration** — the failure is not a browser reaching IBKR, it is an endpoint that "refreshes
from the broker because the projection is stale".

---

## 2. Closed vocabularies

**Every vocabulary below is closed.** A value outside it is rejected at the boundary rather than
rendered, and a new member is added by an ADR rather than by an implementation.

### 2.1 `AvailabilityState`

```text
AVAILABLE                   a real value, with its as-of time
NOT_YET_AVAILABLE           the feed is specified; its dependency is unsatisfied
NOT_IMPLEMENTED             the producing subsystem does not exist
NOT_AUTHORIZED              the producing operation exists and may not run
UNEVALUATED                 the question has not been assessed
STALE                       a value exists and is older than its freshness contract
PARTIAL                     part of the requested extent is present
ERROR                       production failed, and the failure is reported
NOT_APPLICABLE              the question does not apply to this subject
EMPTY_VERIFIED              the producer ran and the correct answer is nothing
INSUFFICIENT_OBSERVATIONS   a value is computable and would not be meaningful
```

**Availability is a typed field, never an overloaded number.** A numeric null does not carry an
availability meaning, and **a missing value is never converted to zero, healthy, passed or no
incidents**.

### 2.2 `DataProvenance`

```text
SYNTHETIC            repository-owned deterministic fixture
SYSTEM_RECORDED      produced by KalpaMani's own deterministic runtime
BACKTEST_SIMULATED   produced by an authorized research run -- hypothetical, never realized
BROKER_REPORTED      observed from a brokerage under an authorized session
```

### 2.3 `DataClassification`

```text
PUBLIC_SAFE            public repository, public demonstration, external hosting
PRIVATE_OPERATIONAL    the approved private deployment boundary only
LICENSED_DERIVED       the approved private deployment boundary only
UNCLASSIFIED           nowhere -- it FAILS CLOSED
CONTROL                REFUSED AT ADMISSION -- CONTROL publication remains DEFERRED
```

### 2.4 `HostingBoundary`

```text
PUBLIC_EDGE        externally hosted; admits PUBLIC_SAFE with SYNTHETIC provenance ONLY
PRIVATE_BOUNDARY   inside the approved private deployment boundary
```

**A server-side render, an API proxy, an edge cache and a build-time fetch are each a copy.** An
externally hosted deployment must not silently receive a licensed payload through any of them.

### 2.5 `MaturityStage`

```text
RESEARCH   SHADOW   AUTOMATED_PAPER   MICRO_LIVE   SCALED_LIVE
```

Mapped to ADR-0026 lifecycle values and to the runtime `Environment` enum in
[`COCKPIT_FEEDBACK_EXTENSION.md`](../architecture/COCKPIT_FEEDBACK_EXTENSION.md) §4.1. **The runtime
enum is unchanged.**

### 2.6 Brain decision states — consumed, never extended

```text
READY_FOR_RISK_REVIEW   WATCHLIST   REJECTED   BLOCKED_DATA   BLOCKED_EVENT
BLOCKED_AI              BLOCKED_CONTRADICTION   BLOCKED_BORROW
```

This vocabulary belongs to
[ADR-0026](../decisions/ADR-0026-strategy-brain-architecture-and-governance.md) §7 and is **consumed
unchanged**. `MAYBE`, `BUY`, `SELL`, `EXECUTE` and `APPROVED_ORDER` remain **refused by name**.

### 2.7 `DownstreamStage` — a separate axis, owned by separate layers

```text
RISK_REVIEW_PENDING    RISK_APPROVED    RISK_REJECTED
ORDER_SUBMITTED        ORDER_ACKNOWLEDGED   ORDER_PARTIALLY_FILLED
ORDER_FILLED           ORDER_CANCELLED      ORDER_REJECTED
```

**This is not an extension of the Brain vocabulary and must never be merged into it.** A funnel
presents the two axes side by side; a single combined status would make it impossible to tell, from
a status alone, whether the Brain or the execution layer produced it. Every member is
`NOT_IMPLEMENTED` in V1, because no portfolio, risk or execution runtime exists.

### 2.8 Strategy health states — consumed, never extended

```text
HEALTHY   WATCH   DEGRADED   NEW_ENTRIES_REDUCED   NEW_ENTRIES_DISABLED
SUSPENDED   RETIRED
```

ADR-0026 §13 owns this vocabulary.

### 2.9 Information-set profiles — consumed, never extended

```text
PUBLIC_PIT   PROVIDER_REALISTIC_PIT   FORWARD_SYSTEM
```

Used exactly as [ADR-0005](../decisions/ADR-0005-point-in-time-data-architecture.md) and the
point-in-time contract define them. **No default profile is invented**; a profile is declared, never
inferred.

---

## 3. The shared envelope

**Every read-model response carries the same envelope.** A field that is optional for a particular
view is present and typed rather than absent, so a consumer never has to guess whether an absence
means "not applicable" or "forgot".

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | string | the read-model schema version. **Unknown version is rejected, never coerced** |
| `api_version` | string | the endpoint contract version, from the URL path |
| `entity_id` | string | a **safe internal** identifier. Never a broker order id, account id, execution identifier or vendor key |
| `correlation_id` | string | ties a response to the request and to the projection run that produced it |
| `source_refs` | list of reference | classified references to the source facts and events. **References, never payloads** |
| `event_time` | instant | when the underlying thing happened |
| `observed_time` | instant | when KalpaMani first observed it |
| `as_of_time` | instant | the point-in-time instant the answer is resolved as of |
| `projected_time` | instant | when this projection row was built |
| `environment` | `Environment` | the runtime environment that produced the underlying facts |
| `maturity_stage` | `MaturityStage` | the governance stage of the strategy version involved, where applicable |
| `provenance` | `DataProvenance` | where the numbers came from |
| `availability` | `AvailabilityState` | whether there is an answer at all |
| `availability_reason` | closed reason code | **why**, from a closed vocabulary — never free text |
| `freshness` | duration + contract | age, and the freshness contract it is measured against |
| `coverage` | ratio + extent | how much of the requested extent is present |
| `completeness` | closed enum | `COMPLETE`, `PARTIAL` or `UNKNOWN` |
| `snapshot_version` | string | the projection snapshot this row belongs to |
| `watermark` | instant | the source position the projection has consumed to |
| `classification` | `DataClassification` | what may be done with this payload |
| `access_scope` | closed enum | which authorization the caller needed |
| `metric_definition_version` | string | the metric dictionary version every number obeys |
| `pins` | object | strategy, factor, risk-policy, entry-policy, exit-policy, model, prompt and code identities, where applicable |

**Illustrative shape — not runtime code:**

```text
ReadModelEnvelope {
    schema_version              "cockpit.executive_overview.v1"
    api_version                 "v1"
    entity_id                   safe internal id
    correlation_id              request/projection correlation id
    source_refs                 [ { ref_id, ref_kind, classification } ]
    event_time / observed_time / as_of_time / projected_time
    environment                 RESEARCH | PAPER | LIVE
    maturity_stage              RESEARCH | SHADOW | AUTOMATED_PAPER | MICRO_LIVE | SCALED_LIVE
    provenance                  SYNTHETIC | SYSTEM_RECORDED | BACKTEST_SIMULATED | BROKER_REPORTED
    availability                <AvailabilityState>
    availability_reason         <closed reason code>
    freshness                   { age, contract_max_age }
    coverage                    { present, requested }
    completeness                COMPLETE | PARTIAL | UNKNOWN
    snapshot_version            projection snapshot id
    watermark                   source position consumed
    classification              <DataClassification>
    access_scope                <closed scope>
    metric_definition_version   "metrics.v1"
    pins                        { strategy_version, factor_definition_version, ... }
    payload                     <view-specific>
}
```

**The envelope is not optional and is not stripped for convenience.** A response without provenance
and availability is a number with no provenance and no availability, which is how a synthetic figure
becomes a reported result.

---

## 4. Read-model catalog

Each view names its **owner** — the subsystem whose recorded facts it projects — and its **inputs**.
**A projection never reads outside its declared inputs.**

| Read model | Owner subsystem | Principal inputs | V1 availability |
|---|---|---|---|
| `ExecutiveOverview` | composite | portfolio, risk, health, data quality, operations, governance | `SYNTHETIC` |
| `PerformanceSeries` | portfolio | recorded portfolio valuations and cash flows | `SYNTHETIC` |
| `PerformanceSummary` | portfolio | `PerformanceSeries` plus trade outcomes | `SYNTHETIC` |
| `PositionSnapshot` | portfolio | recorded positions and lots | `SYNTHETIC` |
| `ExposureAggregate` | portfolio / risk | positions, sector, family, factor and correlation maps | `SYNTHETIC` |
| `StrategyPerformance` | strategy | trade outcomes keyed by module and version | `SYNTHETIC` |
| `StrategyHealth` | strategy | recorded health-state transitions and their inputs | `SYNTHETIC` |
| `CandidateFunnel` | Brain | journaled decisions and reason codes | `SYNTHETIC` |
| `CandidateDetail` | Brain | one journaled `CandidateIntent` and its evidence refs | `SYNTHETIC` |
| `MissedOpportunity` | Brain / research | non-entered candidates and registered follow-up windows | `SYNTHETIC` |
| `TradeSummary` | portfolio / execution | trade ledger records | `SYNTHETIC` |
| `TradeDetail` | composite | candidate, risk decision, orders, fills, protection, exit, attribution | `SYNTHETIC` |
| `TradeLifecycle` | execution | ordered lifecycle events for one trade | `SYNTHETIC` |
| `ExecutionQuality` | execution | order and fill events, reference prices | `SYNTHETIC` |
| `ReconciliationStatus` | execution | recorded reconciliation results | `SYNTHETIC` |
| `ResearchRun` | research | immutable research manifests and results | `SYNTHETIC` |
| `ResearchQueueItem` | research | queue records and their triggers | `SYNTHETIC` |
| `HypothesisRegistration` | research | immutable preregistrations plus linked results | `SYNTHETIC` |
| `ChampionChallengerComparison` | research | paired version results and overlap analysis | `SYNTHETIC` |
| `GovernancePacket` | governance | assembled packets | `SYNTHETIC` |
| `DecisionRecord` | governance | recorded human decisions | `SYNTHETIC` |
| `StrategyVersion` | strategy | version registry records | `SYNTHETIC` |
| `DataQuality` | data platform | recorded quality evidence, coverage and lineage | `SYNTHETIC` |
| `SystemJob` | operations | job run records | `SYNTHETIC` |
| `SystemIncident` | operations | incident records | `SYNTHETIC` |
| `AttentionItem` | composite | alerts, health, risk, data quality, governance | `SYNTHETIC` + governance `AVAILABLE` |
| `Alert` | composite | alert records | `SYNTHETIC` |
| `QualificationStatus` | governance | **tracked repository governance facts** | `AVAILABLE` |
| `AuditEvent` | audit | immutable audit events | `SYNTHETIC` |
| `MaturityStatus` | governance | strategy governance records | `SYNTHETIC` |
| `AiContribution` | research | matched-arm results and AI provenance | `SYNTHETIC` |
| `MarketRegime` | data platform | versioned regime context | `SYNTHETIC` |
| `RiskSnapshot` | risk | recorded risk-engine outputs | `SYNTHETIC` |
| `ShortSideSnapshot` | risk | borrow, squeeze and short exposure records | `SYNTHETIC` |
| `FeedbackPipeline` | research | stage records across the loop | `SYNTHETIC` |

**`QualificationStatus` is the only read model whose real inputs exist today**, and they are tracked
repository governance facts — never private qualification evidence.

### 4.1 Selected payload shapes

Illustrative, not runtime code. Full field-level definitions belong to the implementation cycle and
must satisfy the envelope, the vocabularies and the metric dictionary.

```text
TradeSummary.payload {
    trade_id                    stable internal trade identity
    security_ref                safe internal security reference
    direction                   LONG | SHORT
    trade_status                OPEN | CLOSED | PARTIAL
    strategy_module / alpha_family / trade_template
    entry_time / entry_price / exit_time / exit_price
    shares_at_entry             integer
    initial_position_value      money
    realized_pnl                money        -- CLOSED portion only
    unrealized_pnl              money        -- OPEN portion only
    return_pct                  ratio, metric-defined denominator
    r_multiple                  ratio against INITIAL planned risk
    holding_period              duration, metric-defined
    mfe / mae / capture_ratio   metric-defined
    entry_reason / exit_reason  closed reason codes
    stop_outcome                closed vocabulary
    pins                        { strategy_version, factor_definition_version, risk_policy_version }
}

TradeDetail.payload {
    trade_id
    candidate_ref               -> CandidateDetail
    brain_decision_ref          -> journaled CandidateIntent status
    risk_decision_ref           -> portfolio/risk decision record
    order_refs                  -> ordered order records
    fill_refs                   -> ordered fill records
    protection_refs             -> protective order records
    add_refs                    -> pyramid/add records
    exit_ref                    -> exit decision record
    reconciliation_refs         -> reconciliation records
    attribution                 { strategy, factor, regime }
    benchmark_movement          metric-defined, holding-period aligned
    lineage                     { strategy, model, prompt, code, config }
    audit_refs                  -> immutable audit events
    chart_series_ref            -> OHLC series with entry/add/stop/exit markers
}
```

**`TradeDetail` joins by reference.** Every `_ref` is a **safe internal reference** into a
separately owned read model, and resolving one is an authorized read, not a widening of any
producing contract. **No sizing or execution field is added to `CandidateIntent` to make this view
simpler**, and `CandidateDetail` continues to carry none.

---

## 5. Endpoint catalog and versioning

**Every endpoint is read-only.** The catalog contains no verb that changes state, and **no control
route exists**.

```text
GET  /api/v1/executive/overview
GET  /api/v1/executive/attention
GET  /api/v1/executive/what-changed
GET  /api/v1/portfolio/performance
GET  /api/v1/portfolio/positions
GET  /api/v1/portfolio/exposure
GET  /api/v1/portfolio/trades
GET  /api/v1/portfolio/trades/{trade_id}
GET  /api/v1/portfolio/trades/{trade_id}/lifecycle
GET  /api/v1/strategy/performance
GET  /api/v1/strategy/health
GET  /api/v1/strategy/versions
GET  /api/v1/strategy/champion-challenger
GET  /api/v1/signals/funnel
GET  /api/v1/signals/candidates
GET  /api/v1/signals/candidates/{candidate_id}
GET  /api/v1/signals/missed
GET  /api/v1/risk/snapshot
GET  /api/v1/risk/short-side
GET  /api/v1/market/regime
GET  /api/v1/execution/quality
GET  /api/v1/execution/reconciliation
GET  /api/v1/research/runs
GET  /api/v1/research/queue
GET  /api/v1/research/hypotheses
GET  /api/v1/research/ai-contribution
GET  /api/v1/research/feedback-pipeline
GET  /api/v1/governance/packets
GET  /api/v1/governance/decisions
GET  /api/v1/governance/qualification
GET  /api/v1/governance/maturity
GET  /api/v1/system/data-quality
GET  /api/v1/system/jobs
GET  /api/v1/system/incidents
GET  /api/v1/system/alerts
GET  /api/v1/audit/events
GET  /api/v1/search
GET  /api/v1/ask                (bounded, typed analytics -- never arbitrary SQL or code)
```

**Versioning rules.**

| | |
|---|---|
| **path-versioned** | the API version is in the path. A client and a server that disagree fail loudly |
| **schema-versioned per view** | `schema_version` is per read model, so one view can evolve without a global bump |
| **unknown version is rejected** | a response whose `schema_version` the client does not know is **rejected, never rendered and never coerced**. Zod validates at the boundary |
| **additive within a version** | a new optional field is additive; a removal, a rename or a semantic change is a new version |
| **no silent default** | a field absent from a response is not defaulted into existence |

---

## 6. Query semantics

| | |
|---|---|
| **pagination** | stable cursor pagination over a deterministic sort key. **Offset pagination is not used** for growing collections, because a row inserted between pages silently shifts one out |
| **maximum page size** | every collection endpoint declares a maximum; a larger request is refused, not truncated silently |
| **filtering** | typed, against declared filterable fields. An unknown filter is refused rather than ignored — an ignored filter returns a wider result set that looks like an answer |
| **sorting** | declared sortable fields only, with a deterministic tiebreak so two identical requests return identical order |
| **time ranges** | half-open `[from, to)` in UTC, with the display timezone a presentation concern. A range without an explicit `as_of` resolves against the projection watermark, and the response says which |
| **bounded analytics** | every analytical endpoint declares its maximum scanned extent and refuses beyond it. **An unbounded analytical query is not a feature** |
| **environment and source scoping** | required on every query. **There is no unscoped query**, and a scope is never widened server-side |

**Snapshot consistency.** A summary and the detail rows beneath it are served from **one projection
snapshot**, so drilling down cannot show a total that disagrees with its parts. A detail request
carries the parent's `snapshot_version`; if that snapshot has been superseded, the response says so
rather than silently mixing two.

---

## 7. Caching, and the boundaries it must not cross

| | |
|---|---|
| **cache key** | includes `api_version`, `schema_version`, environment, source provenance, access scope, classification and every query parameter. **An environment or provenance omitted from a cache key is a cross-environment leak waiting to happen** |
| **no shared cache across classification** | a `PUBLIC_SAFE` response and a `LICENSED_DERIVED` response never share a cache entry, a cache namespace or a cache tier |
| **no external cache for private data** | `PRIVATE_OPERATIONAL` and `LICENSED_DERIVED` responses are **never** stored in an externally hosted cache or CDN |
| **freshness is data, not policy** | a cached response carries the same `freshness` and `as_of_time` the origin produced. A cache never makes a stale value look fresh |

**Deep links, exports and assistant queries carry the same scoping.** A URL that encodes a filter
encodes its environment and source too, so a shared link cannot open under a different environment
than the one it was captured in.

---

## 8. Correctness under replay, reordering and correction

| | |
|---|---|
| **idempotent projection** | applying the same source event twice produces the same projection row. Projections are keyed by source event identity, not by arrival |
| **out-of-order arrival** | ordering is by `event_time` with `observed_time` retained. A late event updates the projection and **advances no watermark it did not cover** |
| **corrections append** | a correction is a new record with its own time and reason. **The corrected value is not overwritten in place**, and the read model exposes that a correction occurred |
| **provisional versus final** | attribution and economics that may still change are labelled provisional, and the transition to final is itself a recorded event |
| **rebuild without mutation** | a projection rebuilds from source events and **never mutates a source event**. Authoritative audit events and the audit projection are separately identified, so a projection defect is not mistaken for missing history |
| **replay is not history** | replaying a projection reproduces the read model; it does not re-run a decision, re-request a provider or re-submit an order, and no replay path can |

---

## 9. Failure and partial data

**Failures propagate; they do not disappear.**

| Situation | Response |
|---|---|
| one contributing input failed | envelope `availability = PARTIAL`, the failing component named by a closed code, the rest served |
| a whole view failed | `availability = ERROR`, with a closed reason code and no fabricated payload |
| an input is not implemented | `NOT_IMPLEMENTED`, distinctly from `EMPTY_VERIFIED` |
| an input exists but may not run | `NOT_AUTHORIZED`, distinctly from `NOT_IMPLEMENTED` |
| too few observations | `INSUFFICIENT_OBSERVATIONS`, and **no ratio is returned** |

**A composite view reports the availability of each contributing part**, so an executive tile can be
`AVAILABLE` while the page around it is `PARTIAL`, and the reader can see which is which. **No
partial failure is rounded up to success.**

---

## 10. Identifiers, redaction and access control

**Only safe internal identifiers cross the boundary.** The following are **never** placed in a read
model, a URL, a cache key, an export, a log line or a chart label:

```text
brokerage account identifier        account-binding digest
broker-native order id (BrokerId)   credential or token of any kind
AWS account id or ARN               bucket name
secret identifier                   execution identifier or locator key
vendor row or reconstructable derivative of one
private filesystem path             owner personal identifier
```

**Access control is per read model and read-only.** A scope grants the ability to read a named set
of read models at a named classification, and no scope grants a write. **There is no administrative
scope that unlocks a control**, because there is no control.

**Ask KalpaMani inherits every rule in this section** and adds one: **no read model derived from
licensed rows may be transmitted to an external model**, and an `UNCLASSIFIED` payload fails closed
rather than being sent.

---

## 11. Immutable audit and deletable licensed data

Two obligations that must both hold:

| | |
|---|---|
| **governance** | audit history is immutable, so a decision can be reconstructed later |
| **licensing** | licensed vendor data must be destroyable on short notice (`CLAUDE.md` §4.23) |

**They are reconciled by never embedding one in the other.**

```text
an audit event MAY carry     a classified reference · a lineage identifier · a digest of
                             KalpaMani's own record · closed reason codes · versions and pins
an audit event MAY NOT carry a vendor row · a reconstructable derivative of vendor rows ·
                             a licensed payload copied "for convenience"
```

**Deletion uses authorized tombstone semantics.** When referenced licensed content is deleted, the
audit record survives with its reference marked deleted, its deletion authority recorded and its
governance meaning intact. **The governance evidence is preserved; the vendor data is not retained.**
A projection that had cached licensed content is rebuilt without it, and the rebuild is itself
recorded.

---

## 12. Metric dictionary

**One dictionary, versioned as `metric_definition_version`, and every number obeys it.** A screen
that computes its own variant of a metric is a screen reporting a different metric under the same
name.

### 12.1 Rules that apply to every metric

| | |
|---|---|
| **units are explicit** | money in USD; ratios as decimals with the display format a presentation concern; durations in a stated unit |
| **sign convention** | profit positive, loss negative, for both long and short. **A profitable short is positive**, and a short's exposure sign is carried separately from its profit sign |
| **denominator is named** | every ratio names its denominator. A return with an unnamed denominator is not a return |
| **window and timezone** | every window states its calendar basis and its timezone. Daily boundaries follow the stated market calendar, not the viewer's clock |
| **sample versus population** | stated for every dispersion or risk-adjusted measure |
| **cost treatment** | stated: gross, net of commissions, or net of commissions plus spread, slippage and borrow |
| **missingness** | a missing input yields an availability state, **never a zero** |
| **minimum observations** | every metric declares one and returns `INSUFFICIENT_OBSERVATIONS` below it |

### 12.2 The metrics

| Metric | Definition contract |
|---|---|
| **Profit and loss** | realized and unrealized reported **separately** and never summed into one unlabelled figure. Cost treatment stated. **Deposits and withdrawals are not profit** |
| **Return** | states its method for external cash flows — time-weighted for portfolio performance, money-weighted only where explicitly labelled. Denominator, window and timezone named. **A period containing a cash flow is never reported by naive begin/end division** |
| **Exposure** | long, short, gross and net stated separately against a named base. Short exposure is reported as a positive magnitude with its direction labelled |
| **Planned risk** | the deterministic risk the position was opened with, from the risk record. **Not recomputed from current price**, because a metric that drifts with price is not planned risk |
| **Drawdown** | peak-to-trough on the stated equity series, with the series, its frequency and whether it is intraday or close-only all named. Maximum drawdown states its window |
| **Expectancy** | mean outcome per trade in the stated unit, with the unit (currency or R) named and the trade population defined |
| **Profit factor** | gross profit over gross loss, both from closed trades, with cost treatment stated. **Undefined when gross loss is zero** — reported as `NOT_APPLICABLE`, never as infinity or a large number |
| **Win rate** | winners over a **defined** closed-trade population. States whether break-even trades count and in which bucket |
| **Sharpe** | states its return frequency, its annualization factor, its risk-free assumption and its sample-versus-population convention. **Reported with its minimum-observation rule**, because a Sharpe from twelve observations is decoration |
| **R multiple** | outcome divided by **initial** planned risk at entry. The reference is fixed at entry and does not move with a trailing stop; a trade whose initial planned risk is unavailable reports `NOT_APPLICABLE` |
| **Holding period** | entry to exit in the stated unit, on the stated calendar. States whether it is calendar or trading days. An open trade reports elapsed-to-`as_of`, labelled as open |
| **MFE / MAE** | maximum favourable and adverse excursion against entry, on the stated bar frequency, with the price basis named. **Missing bars yield `PARTIAL`**, never an optimistic value |
| **Capture ratio** | realized outcome over MFE, on the same bar frequency and basis. **Undefined when MFE is zero or negative** — `NOT_APPLICABLE` |
| **Slippage** | actual fill against a **named** reference price, with the reference, its timestamp and its side convention stated. Reported per fill and aggregated with its aggregation method named |
| **Latency** | signal-to-order and order-to-fill, from recorded timestamps, with the clock source and its accuracy stated |

### 12.3 The hard cases, decided rather than left open

| | |
|---|---|
| **external cash flows** | handled by the stated return method and **never allowed to appear as trading performance** |
| **realized versus unrealized** | separate figures. A combined figure is labelled as combined and never presented as realized |
| **long and short signs** | profit sign is direction-independent; exposure sign is not. The two are separate fields |
| **fees, borrow and costs** | every performance metric states its cost treatment, and two metrics with different treatments are never compared |
| **partial fills and partial exits** | a trade's economics are weighted by filled quantity at each stage. **A partial exit reduces a trade; it does not close it or create a second one** |
| **changing size** | adds and pyramids are attributed to the same trade with their own timestamps and prices; the position-weighted basis is recorded rather than re-derived |
| **benchmark alignment** | the benchmark series is aligned to the trade or period boundaries actually used, and states whether it is price or total return. **A price-return benchmark is never compared against a total-return portfolio** |
| **corporate-action adjustment** | adjusted prices and actual fill prices are different series and are labelled as such. **An actual fill is never restated by an adjustment factor** |
| **undefined ratios** | a zero denominator yields `NOT_APPLICABLE`. **Never infinity, never a sentinel, never a large number** |
| **provisional versus final attribution** | provisional attribution is labelled, and finalization is a recorded event |
| **insufficient samples** | `INSUFFICIENT_OBSERVATIONS` rather than a computed number |
| **missing price paths** | `PARTIAL` for every path-dependent metric, and the affected metrics are named |

### 12.4 Definitions and authority

**Where an accepted definition already exists in tracked authority, it is used unchanged.** Strategy
capital is **USD 80,000** and is authoritative; broker equity is observed and never participates in
sizing; planned risk per trade, maximum open planned risk, maximum position size and maximum gross
short are the governed research values in `CLAUDE.md` §6, **reproduced for display context and not
changed here**.

**Where this document proposes a presentation definition that does not already exist, it is an
explicit proposal and is labelled as one.** A presentation definition **never silently changes a
strategy or risk policy**, and adopting one for a screen does not adopt it for the risk engine.

**No performance figure is invented anywhere in this document, and no strategy is described as
validated.**

---

## 13. What this document does not do

```text
implements NOTHING                        authorizes NOTHING
creates no module under src/              creates no database or migration
builds no API                             installs no dependency
reads no provider data                    reads no private artifact
contacts no broker                        touches no AWS or Terraform
changes no runtime enum                   changes no risk or capital value
claims no alpha                           establishes no expected return
```

**Every schema block above is illustrative shape, not runtime code.**

```text
Cockpit read-model implementation:       NOT STARTED / NOT AUTHORIZED
P1-P9:                                   UNEVALUATED
G1 / G2:                                 OPEN / OPEN
provider selected:                       NONE
Phase 3:                                 NOT COMPLETE
CONTROL:                                 DEFERRED
live trading:                            HARD-DISABLED
```

**Specification, implementation, research, deployment and execution are five separate gates.**
