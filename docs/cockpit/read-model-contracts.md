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
**Amended by** [ADR-0028](../decisions/ADR-0028-cockpit-contract-completion-and-boundary-corrections.md) — §2.2, §2.4, §4, §5, §7, §10, §11 and §12.
ADR-0028 is **PROPOSED and carries no authority while the pull request introducing it, PR #72, is open**,
and the corrections it makes here are proposed with it.

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
REPOSITORY_TRACKED   a real fact read from tracked repository authority -- an ADR state, a
                     gate state, a recorded governance status. REAL, and never relabelled
                     SYNTHETIC
SYSTEM_RECORDED      produced by KalpaMani's own deterministic runtime
BACKTEST_SIMULATED   produced by an authorized research run -- hypothetical, never realized
BROKER_REPORTED      observed from a brokerage under an authorized session
```

**`REPOSITORY_TRACKED` exists because `QualificationStatus` is real and is not synthetic.** Its
inputs are facts already published in this public repository — merged ADR states, gate states,
phase state — and calling them `SYNTHETIC` would be false, while calling them `SYSTEM_RECORDED`
would claim a runtime produced them. **A real fact is never relabelled to fit a hosting rule.**

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
PUBLIC_EDGE        externally hosted; admits PUBLIC_SAFE payloads ONLY, and within that only
                   SYNTHETIC or REPOSITORY_TRACKED provenance
PRIVATE_BOUNDARY   inside the approved private deployment boundary
```

**`PUBLIC_EDGE` admits exactly two provenances, and refuses the other three.** `SYSTEM_RECORDED`,
`BACKTEST_SIMULATED` and `BROKER_REPORTED` are **never** admitted to an externally hosted
deployment, whatever their classification: a real operating figure is not made publishable by being
labelled safe. `REPOSITORY_TRACKED` is admitted only from the read models §7.1 enumerates, and only
under the release authorization §7.1 requires.

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
[ADR-0026](../decisions/ADR-0026-strategy-brain-architecture-and-governance.md)'s
[Brain specification](../phase4/strategy-brain-specification.md) §7 and is **consumed
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

ADR-0026's Brain specification §13 owns this vocabulary.

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
| `freshness` | `FreshnessReport` | **source-data age and projection lag as separate numbers**, per required input, against each input's own contract. §3.1 defines it, and a rebuild never makes an old source fact fresh |
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
    freshness                   <FreshnessReport>   -- see §3.1; NEVER one number
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

### 3.1 Freshness — six times, and a rebuild is not one of them

**`as_of_time − newest contributing projected_time` is not freshness.** `projected_time` is when the
projection was *built*, so that difference measures how recently a machine ran, and **rebuilding a
projection over week-old source data would report it as seconds old**. It can also go **negative**,
because a historical `as_of` query resolves as of an instant that precedes the build. A screen
reading it sees a fresh number and stale data.

**Six distinct times, and none of them is a synonym for another.**

| | |
|---|---|
| `evaluation_time` | when the answer was computed — the request instant. **Always known** |
| `as_of_time` | the point-in-time instant the answer is resolved **as of**. Often the same as `evaluation_time`; deliberately earlier for a historical query. **Always known** |
| `source_effective_time` | when the source fact **was true**. A fill's execution instant, a valuation's close, a governance record's effective date |
| `source_observation_time` | when KalpaMani **first observed** the source fact. Never earlier than `source_effective_time`, and the gap between them is the source's own reporting delay |
| `projected_time` | when this projection row was **built**. **Always known** |
| `source_watermark` | the source position the projection has **consumed to** — the boundary beyond which this row knows nothing |

**Three ages, computed from those, and reported separately.**

```text
source_age       = evaluation_time - source_effective_time      -- how old the FACTS are
projection_lag   = projected_time  - source_effective_time      -- how far the BUILD lags
build_age        = evaluation_time - projected_time             -- how old the BUILD is

source_age is the freshness question. A rebuild resets build_age and NEVER source_age.
```

**Units are whole seconds, on UTC instants**, with a monotonic clock used wherever one is available
for a duration; **calendar arithmetic is never used to measure an age**.

**Every required input is evaluated on its own, against its own contract.** A composite view holds
several required inputs with different tolerances — a position mark that is stale after a minute, a
governance record that is current for a month — and **a single "newest contributing" number reports
the freshest and conceals the rest**. So:

| | |
|---|---|
| **per input** | each required input reports its own `source_age`, its own `contract_max_age` and its own resulting state |
| **the composite** | reports the **oldest** required input, names it, and takes the **worst** state any required input reached. **One fresh input never raises the composite** |
| **optional inputs** | are reported and **do not** set the composite state, and which inputs are required is declared per read model, never inferred |
| **the state** | `AVAILABLE` while every required input is inside its own contract; `STALE` with `UPSTREAM_INPUT_STALE` as soon as any one is outside it |

**Missing, skewed and future timestamps refuse rather than resolve.**

| Situation | Result |
|---|---|
| an input carries **no usable source time** | `NOT_YET_AVAILABLE` with `SOURCE_TIMESTAMP_MISSING`. **Its age is unknown, not zero**, and it is never treated as fresh |
| a source time is **later than `evaluation_time`** beyond the declared tolerance | `NOT_YET_AVAILABLE` with `CLOCK_UNSYNCHRONIZED`. **A negative age is never clamped to zero and never rendered** |
| a source time is later by **less than** the declared tolerance | reported as an age of zero **and flagged**, because a small skew is ordinary and a silent one is not |
| two contributing clocks are **not known to be synchronized** | `CLOCK_UNSYNCHRONIZED`, exactly as §12.4 already requires of latency |
| the requested extent is **partly covered** | `PARTIAL` against the `source_watermark`, which says what the row does not know |

**`FreshnessReport`, the envelope's shape.**

```text
FreshnessReport {
    inputs            [ { input_id: SafeId, required: boolean,
                          source_effective_time: Instant or ABSENT,
                          source_observation_time: Instant or ABSENT,
                          source_age: MetricValue,        -- unit SECONDS
                          contract_max_age: Duration,     -- THIS input's own contract
                          state: AvailabilityState, reason: FieldReasonCode } ]
    oldest_required   SafeId or ABSENT   -- the input the composite is reported against
    source_age        MetricValue        -- the oldest REQUIRED input's age
    projection_lag    MetricValue
    build_age         MetricValue
    composite_state   AvailabilityState  -- the WORST state any required input reached
}
```

**A cache serves a response; it does not stop time.** §7's rule that a cached response carries the
`freshness` the origin produced is about **not overwriting** it — not about freezing it. A cached
`source_age` was computed at the origin's `evaluation_time`, so **a cache entry states that instant
and its own maximum age, and a consumer reads the age as of that instant rather than as of now.**

```text
a cached response NEVER re-reports source_age as though it were computed now
a cache entry's maximum lifetime is at most the strictest contract_max_age it carries
an AVAILABLE classification EXPIRES with the entry -- it is never frozen AVAILABLE while
    the source ages behind it, which is how a screen shows a green tile over dead data
```

**Two worked cases, so the separation is checkable.**

```text
CASE 1 -- a rebuild does not refresh a fact
    evaluation_time         12:00      source_effective_time   11:00
    projected_time          11:59
    source_age              3600 s     -- SIXTY MINUTES, and that is the freshness answer
    projection_lag          3540 s     build_age  60 s
    the OLD formula would have reported 60 s and called week-old data fresh

CASE 2 -- one fresh input does not conceal a stale one
    evaluation_time         12:00
    input A (required)      as-of 11:58   source_age    120 s   contract  300 s   AVAILABLE
    input B (required)      as-of 11:00   source_age   3600 s   contract  600 s   STALE
    oldest_required         input B
    source_age              3600 s
    composite_state         STALE, with UPSTREAM_INPUT_STALE, naming input B
    the OLD formula would have reported input A and rendered the view AVAILABLE
```

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
| `WhatChangedEntry` | composite | recorded change events across the subsystems above | `SYNTHETIC` + governance `AVAILABLE` |
| `CandidateSummary` | Brain | journaled candidate decisions, one row per candidate | `SYNTHETIC` |
| `SearchResultPage` | composite | indexed safe identifiers and titles of authorized read models | `SYNTHETIC` + governance `AVAILABLE` |
| `AskAnswer` | composite | bounded typed analytics over authorized read models | `SYNTHETIC` |

**Every endpoint in §5 resolves to a read model in this catalog**, and every read model here has a
payload contract in §4.5. A route with no read model, or a read model with no contract, is a gap
rather than a deferral.

**`QualificationStatus` is the only read model whose payload is composed entirely of real inputs
that exist today**, and they are tracked repository governance facts — never private qualification
evidence. `AttentionItem`, `WhatChangedEntry` and `SearchResultPage` may each carry
governance-derived entries drawn from those same tracked facts; **every other part of them is
`SYNTHETIC`**, and the two kinds are never blended inside one figure.

### 4.1 How to read a field contract

**Every field below carries four things**, and a field missing any of them is not a contract.

| | |
|---|---|
| **type** | a primitive, a closed enum, or one of the reusable types in §4.2. A type is never `object`, never `any` and never "whatever the producer sends" |
| **unit** | stated wherever a number could be read in more than one unit — currency, ratio, basis point, share, second, trading day. **A bare number with no unit is not a contract** |
| **requiredness** | `required` (always present), `conditional` (present exactly when its stated condition holds), or `optional` (may legitimately be absent for this view). **`optional` is never used to make a missing producer look intentional** |
| **absence** | what a consumer reads when there is no value. Every nullable field is a `MetricValue`-shaped wrapper carrying its own `AvailabilityState` and closed reason code — **never a bare `null`, and never a zero** |

**Requiredness and availability are different questions.** `required` means the *field* is always present in the payload; `availability` inside it says whether that field has a *value*. A required field whose producer does not exist is present, `NOT_IMPLEMENTED`, and carries the reason code that says so.

**Reason codes are closed and per-field.** The envelope's `availability_reason` explains the response; a field's reason explains that field. The two are never merged, because a page can be `PARTIAL` for one tile's reason and each tile still has its own.

```text
FieldReasonCode -- closed, and extended only by an ADR

NONE                         nothing is wrong. The value is present and nothing is withheld
EMPTY_RESULT_VERIFIED        the producer ran and the correct answer is nothing
EXTENT_PARTIALLY_COVERED     part of the requested extent is present and part is not
EXTENT_NOT_DETERMINABLE      the requested extent cannot be resolved, so coverage has no
                             denominator
NOT_YET_ASSESSED             the question has not been put to a producer at all
PRODUCER_NOT_IMPLEMENTED     the subsystem that would compute this does not exist
PRODUCER_NOT_AUTHORIZED      it exists and may not run
UPSTREAM_INPUT_MISSING       a declared input was absent
UPSTREAM_INPUT_STALE         a declared input is older than its freshness contract
SOURCE_TIMESTAMP_MISSING     an input carries no usable source time, so its age is unknowable
CLOCK_UNSYNCHRONIZED         two contributing clocks are not known to be synchronized, or a
                             source time is later than the evaluation time beyond tolerance
PRICE_PATH_INCOMPLETE        a path-dependent value cannot be computed from the bars held
CORPORATE_ACTION_UNRESOLVED  an action in the window has no resolved treatment
BELOW_MINIMUM_OBSERVATIONS   the metric's declared minimum is not met
DENOMINATOR_ZERO             the ratio is mathematically undefined for this subject
NOT_DEFINED_FOR_SUBJECT      the question does not apply to this subject at all
POLICY_REFERENCE_MISSING     a separately governed policy value has no versioned reference
CLASSIFICATION_WITHHELD      the value exists and this caller's scope may not read it
PROJECTION_ERROR             production failed, and the failure is reported
```

#### 4.1.1 The validity matrix — state, reason and value together

**Availability and reason are two separate typed axes, and neither is ever spelled in the other's
vocabulary.** `AvailabilityState` answers *is there an answer?*; `FieldReasonCode` answers *why?*.
`UPSTREAM_INPUT_MISSING` is a **reason** and is never written where a state belongs; `NOT_IMPLEMENTED`
is a **state** and is never written where a reason belongs; and `UNKNOWN` belongs to `completeness`
and is **not** an availability value at all. **A field crossing the two axes is refused at the
boundary rather than rendered.**

**Every `MetricValue` carries a reason, always — including a successful one.** The reason a
successful value carries is `NONE`, which exists so a producer never has to invent a failure to fill
a required field. **A fabricated failure reason on a good value is a false report**, and so is a
blank, an empty string or free text.

**This matrix is exhaustive**, and a combination absent from it is invalid.

| `availability` | `value` | Permitted `reason` |
|---|---|---|
| `AVAILABLE` | **present** | `NONE` — and nothing else |
| `STALE` | **present**, with the `as_of` it was true at | `UPSTREAM_INPUT_STALE` — and nothing else |
| `PARTIAL` | **present**, and never read as complete: `coverage` states how much of the extent it covers | `EXTENT_PARTIALLY_COVERED`, `UPSTREAM_INPUT_MISSING`, `UPSTREAM_INPUT_STALE`, `PRICE_PATH_INCOMPLETE`, `CORPORATE_ACTION_UNRESOLVED` |
| `EMPTY_VERIFIED` | **present and empty** — an empty list, or a count of zero. **The only state in which a zero is a correct answer** | `EMPTY_RESULT_VERIFIED` — and nothing else |
| `NOT_YET_AVAILABLE` | **absent** | `UPSTREAM_INPUT_MISSING`, `SOURCE_TIMESTAMP_MISSING`, `CLOCK_UNSYNCHRONIZED`, `PRICE_PATH_INCOMPLETE`, `CORPORATE_ACTION_UNRESOLVED`, `EXTENT_NOT_DETERMINABLE`, `POLICY_REFERENCE_MISSING` |
| `NOT_IMPLEMENTED` | **absent** | `PRODUCER_NOT_IMPLEMENTED` — and nothing else |
| `NOT_AUTHORIZED` | **absent** | `PRODUCER_NOT_AUTHORIZED`, `CLASSIFICATION_WITHHELD` |
| `UNEVALUATED` | **absent** | `NOT_YET_ASSESSED` — and nothing else |
| `INSUFFICIENT_OBSERVATIONS` | **absent** — §9 already refuses to return a ratio below its minimum | `BELOW_MINIMUM_OBSERVATIONS` — and nothing else |
| `NOT_APPLICABLE` | **absent** | `NOT_DEFINED_FOR_SUBJECT`, `DENOMINATOR_ZERO` — and nothing else |
| `ERROR` | **absent** | `PROJECTION_ERROR` — and nothing else |

**`NOT_APPLICABLE` has exactly two routes, and they are different questions.**

| | |
|---|---|
| `NOT_DEFINED_FOR_SUBJECT` | **the subject** does not have this property. An R multiple on a trade that never opened; a strategy pin on a row no strategy produced |
| `DENOMINATOR_ZERO` | **the arithmetic** is undefined. A profit factor with zero gross loss; a capture ratio with a non-positive MFE. **Never infinity, never a sentinel, never a large number** |

**Nothing else reaches `NOT_APPLICABLE`, and `UPSTREAM_INPUT_MISSING` in particular never does.**
**Inapplicability is a property of the subject or of the arithmetic, not a synonym for "we do not
have it"** — collapsing them is how a screen reports that a question does not apply when the truth
is that nobody answered it. A value that is merely absent is `NOT_YET_AVAILABLE`, `NOT_IMPLEMENTED`,
`NOT_AUTHORIZED`, `UNEVALUATED`, `INSUFFICIENT_OBSERVATIONS` or `ERROR`, carrying the reason code
that says why.

**A value-bearing state still carries its value.** `STALE` and `PARTIAL` are answers with a
qualification, not absences: a consumer that renders them as missing is discarding data, and a
consumer that renders them as `AVAILABLE` is overstating it. **Both are rendered distinctly from
each other and from `AVAILABLE`.**

---

### 4.2 Reusable defined types

**Defined once, used everywhere.** A view that redefines one of these is defining a second type with the same name.

```text
SafeId          string      a safe internal identifier. NEVER a broker order id, an account
                            id, an execution identifier, a locator key or a vendor key
Instant         string      RFC 3339 UTC instant, millisecond precision
DateOnly        string      ISO 8601 calendar date. NEVER widened into an instant
Duration        integer     whole seconds, unless a field states another unit
TradingDays     integer     whole trading days on the named market calendar
Money           object      { amount: decimal string, currency: "USD" }. Decimal string,
                            never binary floating point
Ratio           object      { value: decimal string, denominator: <closed name> }.
                            A ratio with no named denominator is refused at the boundary
Bps             object      { value: decimal string, scale: integer }. SIGNED basis
                            points -- one basis point is one ten-thousandth, so a ratio
                            becomes Bps by multiplying by 10,000. A decimal string with a
                            stated scale, NEVER a bare integer: truncating 8.4 bps to 8
                            discards four tenths of a basis point on every fill, and an
                            aggregate over fifty thousand fills carries the whole of it
Quantity        integer     whole shares. Signed only where the field says so
SignedMoney     object      Money plus an explicit sign convention: profit positive,
                            loss negative, for both long and short
Magnitude       object      Money or Quantity plus a separate `direction` of LONG or SHORT.
                            Exposure carries magnitude and direction; it never carries a
                            profit sign
Percent         Ratio       a Ratio whose denominator is named and whose display format is
                            a presentation concern
MetricValue     object      { value: <typed value or absent>, unit: <closed unit>,
                              availability: AvailabilityState, reason: FieldReasonCode,
                              as_of: Instant, metric_id: <dictionary key>,
                              metric_definition_version: string }
                            The ONLY wrapper a nullable number arrives in
CountValue      MetricValue a MetricValue whose unit is COUNT and whose value is an integer
RecordValue     object      { record: <the named record type, or ABSENT>,
                              availability: AvailabilityState, reason: FieldReasonCode,
                              as_of: Instant or ABSENT }
                            The ONLY wrapper a nested record arrives in. The record is
                            present exactly when the availability state is value-bearing
                            under the §4.1.1 matrix, and is ABSENT otherwise -- never a
                            skeleton, never a placeholder, and never a zeroed record
Ref             object      { ref_id: SafeId, ref_kind: <closed RefKind>,
                              resolution: <closed Resolution>, classification:
                              DataClassification }
RefList         object      { items: [Ref], cardinality: <closed Cardinality>,
                              total: CountValue, truncated: boolean }
                            A list of references states how many there are, so a truncated
                            list is never read as a complete one
VersionPins     object      { strategy_version, factor_definition_version,
                              risk_policy_version, entry_policy_version,
                              exit_policy_version, model_version, prompt_version,
                              code_identity, config_identity }
                            Each a SafeId or a MetricValue carrying NOT_APPLICABLE with
                            NOT_DEFINED_FOR_SUBJECT where a pin genuinely does not apply
PolicyRef       object      { policy_id: SafeId, policy_version: string,
                              as_of: Instant }. A separately governed policy value is
                            ALWAYS carried with its versioned reference, and a value whose
                            reference is missing is POLICY_REFERENCE_MISSING, never a
                            number
SeriesPoint     object      { t: Instant or DateOnly, v: MetricValue }
Series          object      { points: [SeriesPoint], granularity: <closed enum>,
                              calendar: <closed market calendar>, timezone: "UTC",
                              coverage: { present, requested }, completeness: COMPLETE |
                              PARTIAL | UNKNOWN }
ReasonCoded     object      { code: <closed vocabulary member>, vocabulary: <name>,
                              vocabulary_version: string }. No free text, anywhere
```

**Closed helper vocabularies.**

```text
Cardinality     EXACTLY_ONE   ZERO_OR_ONE   ZERO_OR_MORE   ONE_OR_MORE
Resolution      ENDPOINT      -- resolvable by a catalogued GET, named in §4.3
                EMBEDDED      -- the referenced payload is already inside this response
                AUTHORIZED_READ -- resolvable only by a caller holding the named scope
                UNRESOLVABLE_V1 -- the producing subsystem does not exist; the reference is
                                   carried so the join is specified, and it resolves to an
                                   availability state rather than to a payload
Unit            USD  RATIO  PERCENT  BPS  SHARES  SECONDS  TRADING_DAYS  CALENDAR_DAYS
                COUNT  R_MULTIPLE  DIMENSIONLESS
```

---

### 4.3 Resolving a reference — no dangling `_ref`

**Every reference names how it resolves, and nothing resolves by convention.** A `_ref` whose
resolution is not in this table is refused at the boundary.

| `ref_kind` | Resolves to | Resolution | Cardinality |
|---|---|---|---|
| `candidate` | `CandidateDetail` | `ENDPOINT` — `GET /api/v1/signals/candidates/{candidate_id}` | `ZERO_OR_ONE` |
| `brain_decision` | the journaled decision status inside `CandidateDetail` | `EMBEDDED` | `EXACTLY_ONE` |
| `risk_decision` | `RiskSnapshot.decisions[]` | `AUTHORIZED_READ` — `risk:read` | `ZERO_OR_ONE` |
| `order` | `TradeLifecycle` order events | `ENDPOINT` — `GET /api/v1/portfolio/trades/{trade_id}/lifecycle` | `ZERO_OR_MORE` |
| `fill` | `TradeLifecycle` fill events | `ENDPOINT` — the same lifecycle response | `ZERO_OR_MORE` |
| `protection` | `TradeLifecycle` protective-order events | `ENDPOINT` — the same lifecycle response | `ZERO_OR_MORE` |
| `add` | `TradeLifecycle` add and pyramid events | `ENDPOINT` — the same lifecycle response | `ZERO_OR_MORE` |
| `exit` | `TradeLifecycle` exit event | `ENDPOINT` — the same lifecycle response | `ZERO_OR_ONE` |
| `reconciliation` | `ReconciliationStatus` | `ENDPOINT` — `GET /api/v1/execution/reconciliation` | `ZERO_OR_MORE` |
| `execution_quality` | `ExecutionQuality` | `ENDPOINT` — `GET /api/v1/execution/quality` | `ZERO_OR_ONE` |
| `strategy_version` | `StrategyVersion` | `ENDPOINT` — `GET /api/v1/strategy/versions` | `EXACTLY_ONE` |
| `health_transition` | `StrategyHealth` transitions | `ENDPOINT` — `GET /api/v1/strategy/health` | `ZERO_OR_MORE` |
| `research_run` | `ResearchRun` | `ENDPOINT` — `GET /api/v1/research/runs` | `ZERO_OR_MORE` |
| `registration` | `HypothesisRegistration` | `ENDPOINT` — `GET /api/v1/research/hypotheses` | `ZERO_OR_ONE` |
| `queue_item` | `ResearchQueueItem` | `ENDPOINT` — `GET /api/v1/research/queue` | `ZERO_OR_MORE` |
| `packet` | `GovernancePacket` | `ENDPOINT` — `GET /api/v1/governance/packets` | `ZERO_OR_ONE` |
| `decision` | `DecisionRecord` | `ENDPOINT` — `GET /api/v1/governance/decisions` | `ZERO_OR_MORE` |
| `audit_event` | `AuditEvent` | `AUTHORIZED_READ` — `audit:read`, `GET /api/v1/audit/events` | `ZERO_OR_MORE` |
| `evidence` | a classified evidence artefact | `AUTHORIZED_READ` — the scope named on the reference | `ZERO_OR_MORE` |
| `chart_series` | an OHLC `Series` with markers | `AUTHORIZED_READ` — `market:read`; `UNRESOLVABLE_V1` | `ZERO_OR_ONE` |
| `benchmark_series` | a benchmark `Series` | `AUTHORIZED_READ` — `market:read`; `UNRESOLVABLE_V1` | `ZERO_OR_ONE` |
| `regime_context` | `MarketRegime` | `ENDPOINT` — `GET /api/v1/market/regime` | `ZERO_OR_ONE` |
| `data_quality` | `DataQuality` | `ENDPOINT` — `GET /api/v1/system/data-quality` | `ZERO_OR_MORE` |
| `incident` | `SystemIncident` | `ENDPOINT` — `GET /api/v1/system/incidents` | `ZERO_OR_MORE` |
| `alert` | `Alert` | `ENDPOINT` — `GET /api/v1/system/alerts` | `ZERO_OR_MORE` |
| `source_fact` | the recorded fact a projection was built from | `AUTHORIZED_READ` — the scope named on the reference | `ONE_OR_MORE` |

**`UNRESOLVABLE_V1` is a stated resolution, not a gap.** It says the join is specified and the
producer does not exist, so a caller receives an `AvailabilityState` and a reason code rather than a
404 it has to interpret. **It is never used for a producer that exists.**

**Resolving a reference is an authorized read, not a widening.** No producing contract gains a field
because a view resolves a reference into it, and **no reference resolves to a payload the caller's
scope may not read** — that is `CLASSIFICATION_WITHHELD`, and the reference stays visible so the
reader knows something exists that they may not see.

**`TradeDetail` joins by reference.** Every `_ref` is a **safe internal reference** into a
separately owned read model, and resolving one is an authorized read, not a widening of any
producing contract. **No sizing or execution field is added to `CandidateIntent` to make this view
simpler**, and `CandidateDetail` continues to carry none.

---

### 4.4 The four risk quantities, kept apart

**"Planned risk" was one word doing four jobs**, and the four are different facts with different
owners, different lifetimes and different truth conditions. A screen that shows one of them under
another's label is asserting something nobody computed.

```text
InitialPlannedRisk {
    risk_money            Money         required, IMMUTABLE
    risk_pct_of_capital   Percent       required, denominator STRATEGY_CAPITAL_AT_ENTRY
    reference_price       Money         required -- the entry reference the risk was set against
    invalidation_ref      Ref           required, kind `evidence` -- the invalidation level
                                        used AT ENTRY, carried as a reference, never an order
    recorded_at           Instant       required -- when the risk record was written
    risk_policy_ref       PolicyRef     required -- the policy version that produced it
    source                enum{RISK_RECORD_AT_ENTRY}   required -- and no other source
}

CurrentOpenPlannedRisk {
    risk_money            MetricValue   required -- unit USD, of the REMAINING exposure
    risk_pct_of_capital   MetricValue   required -- unit PERCENT, denominator
                                        STRATEGY_CAPITAL_AS_OF
    as_of                 Instant       required -- the assessment instant, always displayed
    assessment_ref        Ref           required, kind `risk_decision`
    risk_policy_ref       PolicyRef     required
    protection_state      ReasonCoded   required -- from the protective-order record
    source                enum{RISK_ENGINE_ASSESSMENT}  required
    staleness             enum{FRESH,STALE}             required -- of a PRESENT assessment.
                                        A MISSING assessment has no record at all, and is
                                        carried by the RecordValue wrapper, not by a record
                                        whose required fields nobody could fill
}

PermittedRisk {
    limit_money           MetricValue   required
    limit_pct             MetricValue   required
    policy_ref            PolicyRef     required -- a permitted value NEVER appears without one
    scope                 enum{PER_TRADE_LONG,PER_TRADE_SHORT,OPEN_PORTFOLIO,
                               INDIVIDUAL_POSITION,GROSS_SHORT}   required
}

GapEventRisk {
    modelled_loss         MetricValue   required -- unit USD, a SEPARATE model, never folded
                                        into planned risk
    scenario_ref          Ref           required, kind `evidence`
    model_version         SafeId        required
    as_of                 Instant       required
}
```

**Every one of the four is carried in a `RecordValue`, and never bare.** Each record above states
what it contains **when it exists**; whether it exists is the wrapper's question, answered by the
§4.1.1 matrix. A field declared `initial_planned_risk: RecordValue<InitialPlannedRisk> required`
is **always present in the payload** and carries its record **only when its availability state is
value-bearing**.

**Nothing is invented to fill a required field.** A producing system that has not written a risk
record has produced no `recorded_at`, no `risk_policy_ref`, no `reference_price` and no
`invalidation_ref`, and **a skeleton record carrying a zeroed amount, a synthesised policy
identifier or the response's own timestamp is a fabricated fact wearing a contract's shape**. The
record is `ABSENT`, and the wrapper says why.

**An absent source time is not the response's time.** `as_of_time` and `projected_time` in the
envelope belong to the *response*: the instant the answer was resolved as of, and the instant the
projection row was built. They are always known. A record's own `recorded_at` or `as_of` belongs to
the *source fact*, and when the source fact does not exist neither does its time — the wrapper's
`as_of` is then `ABSENT`, and `SOURCE_TIMESTAMP_MISSING` says so. **Substituting a response time for
a missing source time would date a fact to the moment somebody asked about it.**

| | |
|---|---|
| **initial planned risk is immutable** | it is the entry-time reference and **the only denominator an R multiple may use**. **A moving stop does not move it**, a protective-order change does not move it, and no projection recomputes it from a current price |
| **current open planned risk is an assessment** | it belongs to the risk engine, describes the **remaining** exposure, and is meaningless without its `as_of`. **The Cockpit displays it and computes none of it** |
| **permitted risk is policy** | it is a separately governed value carried with its `PolicyRef`. **A permitted value with no versioned reference is `POLICY_REFERENCE_MISSING`, never a number**, and this specification changes no limit |
| **gap and event risk is modelled separately** | where it applies. It is never added into either planned-risk figure, because a modelled scenario and a recorded plan are different kinds of claim |

**The lifecycle cases, decided rather than left open.**

| Situation | Contract |
|---|---|
| **partial fill** | `InitialPlannedRisk` is recorded against the **filled** quantity at entry, and is written once the entry stage reaches its recorded terminal fill state. An entry still filling carries an **absent** record, availability `NOT_YET_AVAILABLE`, reason `UPSTREAM_INPUT_MISSING`, `as_of` **absent** |
| **partial exit** | `InitialPlannedRisk` is **unchanged** — a partial exit reduces a trade, it does not restate why the trade was opened. `CurrentOpenPlannedRisk` falls with the remaining exposure |
| **add or pyramid** | the add carries **its own** `InitialPlannedRisk` record, at its own reference price and its own as-of. **The trade's original record is retained unchanged**, and the trade-level R methodology is stated in §12.4 |
| **protection change** | recorded as a protective-order event that moves `CurrentOpenPlannedRisk` and **never** `InitialPlannedRisk` |
| **closed portion** | closed and remaining exposure are reported as separate quantities. A fully closed trade carries an **absent** `CurrentOpenPlannedRisk` record, availability `NOT_APPLICABLE`, reason `NOT_DEFINED_FOR_SUBJECT` — there is no remaining exposure for the question to be about — and **retains its `InitialPlannedRisk` record unchanged** |
| **stale assessment** | the record is **present**, `staleness = STALE`, wrapper availability `STALE`, reason `UPSTREAM_INPUT_STALE`, and the value is shown with the `as_of` it was true at. **A stale assessment is never presented as current, and never discarded as missing** |
| **missing assessment** | the record is **absent** and carries no `staleness`, because there is no assessment to describe. Availability is `NOT_YET_AVAILABLE` with `UPSTREAM_INPUT_MISSING`, or `NOT_IMPLEMENTED` with `PRODUCER_NOT_IMPLEMENTED` — whichever is true. **Never zero, never a skeleton record, and never `NOT_APPLICABLE`** |
| **missing initial risk** | the record is **absent**. Availability is `NOT_YET_AVAILABLE` while the entry is still filling, `NOT_IMPLEMENTED` where no risk-record producer exists, or `NOT_YET_AVAILABLE` with `UPSTREAM_INPUT_MISSING` where the historical evidence was never written — **whichever is true. It is unavailable, not inapplicable**, and `NOT_APPLICABLE` is reserved for a subject the question genuinely does not apply to, such as a trade that was never opened |
| **aggregation** | portfolio open planned risk sums `CurrentOpenPlannedRisk` over **open** exposure only, **once per position**. An add is part of its trade and is not counted a second time; a closed portion contributes nothing; and an aggregate containing any `STALE` or missing component is `PARTIAL` with the components named |
| **missing policy reference** | a `PermittedRisk` whose governing policy reference is absent carries an **absent** record, availability `NOT_YET_AVAILABLE`, reason `POLICY_REFERENCE_MISSING`. **A permitted limit is never served under a default nobody approved**, and never as a number with an invented `policy_id` |
| **partially available composite** | a view carrying several of these records reports each wrapper on its own, and the envelope is `PARTIAL` naming the absent ones. **One available record never raises the page to `AVAILABLE`, and one absent record never suppresses the ones that exist** |

**The Cockpit displays these facts and invents no trading permission.** Showing a permitted limit is
not granting it, showing headroom is not authorizing its use, and **no view computes a permitted
exposure**. **This document changes no risk limit, no capital value, no leverage, no sizing rule and
no stop policy** — the governed research values in `CLAUDE.md` §6 are reproduced for display context
and are unchanged.

#### 4.4.1 Six payloads, so the shapes are satisfiable rather than described

**Every combination the contract permits is written out**, because a contract whose unavailable case
nobody drafted is a contract whose unavailable case does not fit. Values are **synthetic**, from the
§4.6 template, and are not results.

```text
1. INITIAL RISK AVAILABLE -- the ordinary case
initial_planned_risk {
    availability  AVAILABLE      reason  NONE      as_of  2026-08-14T14:31:07.000Z
    record {
        risk_money            { amount: "400.00", currency: "USD" }
        risk_pct_of_capital   { value: "0.0050", denominator: STRATEGY_CAPITAL_AT_ENTRY }
        reference_price       { amount: "184.20", currency: "USD" }
        invalidation_ref      { ref_id: <safe id>, ref_kind: evidence,
                                resolution: AUTHORIZED_READ, classification:
                                PRIVATE_OPERATIONAL }
        recorded_at           2026-08-14T14:31:07.000Z
        risk_policy_ref       { policy_id: <safe id>, policy_version: "risk.v1",
                                as_of: 2026-08-01T00:00:00.000Z }
        source                RISK_RECORD_AT_ENTRY
    }
}

2. INITIAL RISK NOT YET AVAILABLE -- the entry is still filling
initial_planned_risk {
    availability  NOT_YET_AVAILABLE   reason  UPSTREAM_INPUT_MISSING   as_of  ABSENT
    record        ABSENT
}
-- the entry stage has not reached its recorded terminal fill state, so no risk record has
-- been written. There is no recorded_at to report, and the response's own times are NOT
-- substituted for one.

3. INITIAL RISK EVIDENCE MISSING -- a historical trade whose record was never written
initial_planned_risk {
    availability  NOT_YET_AVAILABLE   reason  UPSTREAM_INPUT_MISSING   as_of  ABSENT
    record        ABSENT
}
-- indistinguishable in shape from case 2 and different in fact, which is why the trade's
-- own lifecycle state is read alongside it. It is NOT NOT_APPLICABLE: the trade opened, so
-- the question applies and nobody answered it. Every r_multiple over this trade is
-- NOT_YET_AVAILABLE with UPSTREAM_INPUT_MISSING, and is NEVER computed from a current stop.

4. CURRENT ASSESSMENT MISSING -- the risk engine does not exist in V1
open_planned_risk {
    availability  NOT_IMPLEMENTED     reason  PRODUCER_NOT_IMPLEMENTED   as_of  ABSENT
    record        ABSENT
}
-- no staleness is reported, because there is no assessment to call fresh or stale.

5. PERMITTED LIMIT WITH NO POLICY REFERENCE
permitted_open_risk {
    availability  NOT_YET_AVAILABLE   reason  POLICY_REFERENCE_MISSING   as_of  ABSENT
    record        ABSENT
}
-- the number may be knowable and is still not served. A permitted limit without its
-- versioned reference is a limit nobody approved at a version nobody can name.

6. PARTIALLY AVAILABLE COMPOSITE -- one trade row, three wrappers, three answers
envelope        availability PARTIAL   reason EXTENT_PARTIALLY_COVERED
                completeness PARTIAL
                unavailable_components [ open_planned_risk, permitted_risk ]
initial_planned_risk  { availability AVAILABLE,        reason NONE,   record present }
open_planned_risk     { availability NOT_IMPLEMENTED,  reason PRODUCER_NOT_IMPLEMENTED,
                        record ABSENT }
permitted_risk        { availability NOT_YET_AVAILABLE, reason POLICY_REFERENCE_MISSING,
                        record ABSENT }
-- the available record is served in full, the absent ones are named, and the page is not
-- rounded up to AVAILABLE or down to ERROR.
```

**These six are the required cases**, and an implementation that cannot produce all six against its
own schema has not implemented this section.

---

### 4.5 The payload contracts

**Every catalogued read model has a payload contract here.** Each block states the fields, their
types and units; each is followed by its identity, its references, its pins, its classification and
access scope, its freshness and completeness contract, and the invariants a projection must hold.
**Every field not marked `required` states its condition**, and every nullable number is a
`MetricValue`.

**Shared by every payload, and not repeated in each block:** the envelope of §3, the field
conventions of §4.1, the types of §4.2 and the reference resolutions of §4.3. **A payload never
repeats an envelope field**, because two copies of `as_of_time` are two values that can disagree.

#### Executive

```text
ExecutiveOverview.payload {
    strategy_capital          Money         required -- USD 80,000, authoritative
    broker_reported_equity    MetricValue   required -- unit USD, OBSERVED, informational,
                                            and never substituted for strategy capital
    cash                      MetricValue   required -- unit USD
    pnl                       [ { window: enum{DAY,WEEK,MONTH,CUMULATIVE},
                                  realized: MetricValue, unrealized: MetricValue } ]
                                            required, one entry per window; realized and
                                            unrealized are NEVER summed into one
                                            unlabelled figure
    return_pct                MetricValue   required -- unit PERCENT, denominator named,
                                            method TIME_WEIGHTED
    exposure                  { long: Magnitude, short: Magnitude, gross: Magnitude,
                                net: Magnitude }   required
    open_planned_risk         RecordValue<CurrentOpenPlannedRisk>   required
    permitted_open_risk       RecordValue<PermittedRisk>   required -- scope OPEN_PORTFOLIO
    drawdown                  MetricValue   required -- unit PERCENT
    regime_ref                Ref           required, kind regime_context
    system_health             ReasonCoded   required
    data_freshness            MetricValue   required -- unit SECONDS, metric_id
                                            freshness.source_age. The age of the
                                            OLDEST required input, never the
                                            newest and never the build age
    active_strategies         CountValue    required
    open_incidents            CountValue    required
    last_decision             { at: MetricValue, ref: Ref }   required
    last_scout_run            { at: MetricValue, ref: Ref }   required
    what_changed              RefList       required, kind source_fact
    attention                 RefList       required, kind source_fact
    tile_availability         [ { tile_id: SafeId, availability: AvailabilityState,
                                  reason: FieldReasonCode } ]   required -- one entry per
                                            tile, so a PARTIAL page names its failing parts
}
```

**Identity** `entity_id` is the snapshot identity of the overview.
**Pins, classification and access** `VersionPins` where applicable · `PRIVATE_OPERATIONAL`, except
the governance-derived tiles, which are `PUBLIC_SAFE` · scope `executive:read`.
**Freshness and completeness** the contract maximum age is the strictest of its contributing
projections; `completeness = PARTIAL` whenever any contributing tile is not `AVAILABLE`.
**Invariants** strategy capital and broker equity are separate fields and **neither is ever
substituted for the other** · every tile carries its own availability · **no tile renders zero for a
missing input** · the whole payload is served from one `snapshot_version`.

```text
WhatChangedEntry.payload {
    change_id                 SafeId        required
    subject                   ReasonCoded   required -- the closed subject class that changed
    change_kind               ReasonCoded   required
    before                    MetricValue   conditional -- present when a prior value exists
    after                     MetricValue   required
    materiality               ReasonCoded   required
    evidence_refs             RefList       required, kind source_fact
}
```

**Identity** `change_id` · **classification** follows the subject's own classification, and a
governance change is `PUBLIC_SAFE` · **scope** `executive:read` · **invariants** a change with no
resolvable evidence reference is **not rendered**, and a change is never synthesised from the
absence of a value.

```text
AttentionItem.payload {
    item_id                   SafeId        required
    what_happened             ReasonCoded   required
    why_it_matters            ReasonCoded   required
    impact                    MetricValue   required
    evidence_refs             RefList       required, kind evidence or source_fact
    recommended_action        ReasonCoded   required -- a PERMITTED GOVERNANCE action, and
                                            never an execution instruction
    severity                  ReasonCoded   required
    materiality_rank          integer       required
    dedup_key                 SafeId        required -- deduplicated against the alert feed
    first_seen                Instant       required
    last_seen                 Instant       required
    occurrence_count          CountValue    required
}
```

**Identity** `item_id`, stable across occurrences · **classification** the strictest of its
contributing evidence · **scope** `executive:read` · **invariants** **an item missing any of the
five presented things is not rendered** · `recommended_action` is drawn from a closed governance
vocabulary containing **no order, stop, capital, risk, promotion or provider verb** · the Cockpit
performs none of them.

#### Portfolio

```text
PerformanceSeries.payload {
    series_id                 SafeId        required
    granularity               enum{DAILY,WEEKLY,MONTHLY}   required
    calendar                  ReasonCoded   required -- the named market calendar
    equity                    Series        required -- unit USD
    return_series             Series        required -- unit PERCENT, method TIME_WEIGHTED
    drawdown_series           Series        required -- unit PERCENT, basis CLOSE_ONLY or
                                            INTRADAY, stated on the series
    cash_flows                [ { at: Instant, amount: SignedMoney,
                                  kind: enum{DEPOSIT,WITHDRAWAL} } ]   required
    cost_treatment            enum{GROSS,NET_COMMISSIONS,NET_ALL_COSTS}   required
    benchmark_refs            RefList       required, kind benchmark_series
}
```

**Identity** `series_id` · **pins** `metric_definition_version` · **classification**
`PRIVATE_OPERATIONAL` · **scope** `portfolio:read` · **freshness** the contract maximum age is one
completed session on the named calendar · **invariants** **a deposit or withdrawal never appears in
a return or a profit series** · a period containing a cash flow is never reported by naive
begin/end division · **a `BACKTEST_SIMULATED` series and a `SYSTEM_RECORDED` series never share a
`series_id`** · missing points make the series `PARTIAL`, never zero.

```text
PerformanceSummary.payload {
    window                    { from: Instant, to: Instant, calendar: ReasonCoded,
                                timezone: "UTC" }   required, half-open [from, to)
    total_return              MetricValue   required -- PERCENT, TIME_WEIGHTED
    money_weighted_return     MetricValue   conditional -- present only when explicitly
                                            requested, and always labelled as such
    max_drawdown              MetricValue   required -- PERCENT, with its window and basis
    expectancy                MetricValue   required -- unit USD or R_MULTIPLE, stated
    profit_factor             MetricValue   required
    win_rate                  MetricValue   required
    sharpe                    MetricValue   required
    average_winner            MetricValue   required -- unit USD
    average_loser             MetricValue   required -- unit USD
    r_multiple_distribution   [ { bucket: ReasonCoded, count: CountValue } ]   required
    trade_population          ReasonCoded   required -- the defined population every ratio
                                            above is computed over
    minimum_observations_met  boolean       required
    cost_treatment            enum{GROSS,NET_COMMISSIONS,NET_ALL_COSTS}   required
}
```

**Identity** the window plus the population · **pins** `metric_definition_version` ·
**classification** `PRIVATE_OPERATIONAL` · **scope** `portfolio:read` · **invariants** every ratio
names its denominator or returns `INSUFFICIENT_OBSERVATIONS` · **two summaries with different
`cost_treatment` are never compared** · a `profit_factor` with zero gross loss is `NOT_APPLICABLE`
with `DENOMINATOR_ZERO`.

```text
PositionSnapshot.payload {
    position_id               SafeId        required
    security_ref              Ref           required, kind evidence
    direction                 enum{LONG,SHORT}   required
    quantity                  Quantity      required -- shares currently held
    entry_price               MetricValue   required -- unit USD, position-weighted basis
    current_price             MetricValue   required -- unit USD, with its own as_of
    unrealized                SignedMoney   required
    initial_planned_risk      RecordValue<InitialPlannedRisk>       required
    open_planned_risk         RecordValue<CurrentOpenPlannedRisk>   required
    gap_event_risk            RecordValue<GapEventRisk>   conditional -- present where the
                                            model applies
    invalidation_ref          Ref           required, kind evidence -- a REFERENCE to a
                                            level, never an order
    holding_duration          MetricValue   required -- unit TRADING_DAYS
    borrow_state              ReasonCoded   conditional -- required when direction is SHORT;
                                            from a borrow RECORD, never inferred from price
    groupings                 { sector: ReasonCoded, industry: ReasonCoded,
                                strategy_module: ReasonCoded, alpha_family: ReasonCoded,
                                factor_bucket: ReasonCoded,
                                correlation_cluster: ReasonCoded }   required
    trade_ref                 Ref           required, kind source_fact
    pins                      VersionPins   required
}
```

**Identity** `position_id` · **classification** `PRIVATE_OPERATIONAL` · **scope** `portfolio:read` ·
**invariants** **borrow state comes from a record and is never inferred from price behaviour** · an
unknown borrow state renders unknown, **never available** · the two risk quantities are separate
fields and **neither is derived from the other**.

```text
ExposureAggregate.payload {
    grouping                  ReasonCoded   required -- the grouping axis
    buckets                   [ { bucket: ReasonCoded, long: Magnitude, short: Magnitude,
                                  gross: Magnitude, net: Magnitude,
                                  open_planned_risk: RecordValue<CurrentOpenPlannedRisk>,
                                  position_count: CountValue } ]   required
    base                      ReasonCoded   required -- the named base every magnitude is
                                            measured against
    permitted                 [ RecordValue<PermittedRisk> ]   required -- displayed,
                                            never computed
    concentration             MetricValue   required
    correlation_ref           Ref           conditional, kind evidence
}
```

**Identity** the grouping plus the snapshot · **classification** `PRIVATE_OPERATIONAL` · **scope**
`portfolio:read` · **invariants** **a grouping is displayed, never computed as a permitted
exposure** · every magnitude carries a direction and **no exposure carries a profit sign** · a
position contributes to each axis exactly **once**.

#### Trade and execution

```text
TradeSummary.payload {
    trade_id                  SafeId        required
    security_ref              Ref           required, kind evidence
    direction                 enum{LONG,SHORT}   required
    trade_status              enum{OPEN,CLOSED,PARTIALLY_EXITED}   required -- BUSINESS
                                            status only, and never a data-completeness state
    data_completeness         enum{COMPLETE,PARTIAL,UNKNOWN}   required -- a SEPARATE field,
                                            because a complete trade with a missing bar is
                                            not a partially exited trade
    strategy_module           ReasonCoded   required
    alpha_family              ReasonCoded   required
    trade_template            ReasonCoded   required
    entry_time                Instant       required
    entry_price               MetricValue   required -- unit USD, filled-quantity weighted
    exit_time                 MetricValue   conditional -- required when trade_status is
                                            CLOSED; NOT_DEFINED_FOR_SUBJECT while open
    exit_price                MetricValue   conditional -- as exit_time
    shares_at_entry           Quantity      required -- filled at entry, not ordered
    shares_open               Quantity      required
    initial_position_value    Money         required -- unit USD
    realized_pnl              MetricValue   required -- unit USD, CLOSED portion only
    unrealized_pnl            MetricValue   required -- unit USD, OPEN portion only
    return_pct                MetricValue   required -- unit PERCENT, denominator
                                            INITIAL_POSITION_VALUE
    initial_planned_risk      RecordValue<InitialPlannedRisk>       required
    open_planned_risk         RecordValue<CurrentOpenPlannedRisk>   required
    r_multiple                MetricValue   required -- unit R_MULTIPLE, denominator
                                            INITIAL_PLANNED_RISK, per §12.3
    holding_period            MetricValue   required -- unit TRADING_DAYS or CALENDAR_DAYS,
                                            stated on the value
    mfe                       MetricValue   required -- unit USD, bar frequency and price
                                            basis named
    mae                       MetricValue   required -- unit USD, as mfe
    capture_ratio             MetricValue   required -- unit RATIO, denominator MFE
    entry_reason              ReasonCoded   required
    exit_reason               MetricValue   conditional -- required when CLOSED
    stop_outcome              ReasonCoded   required
    environment               Environment   required -- from the envelope, restated nowhere
    pins                      VersionPins   required
    detail_ref                Ref           required, kind source_fact
}
```

**Identity** `trade_id` · **classification** `PRIVATE_OPERATIONAL` · **scope** `portfolio:read` ·
**invariants** **a fill is never counted as a separate trade** · **a partial exit reduces a trade;
it does not close it and does not create a second one** · **business status and data completeness
are separate fields and neither is inferred from the other** · every path-dependent value is
`PARTIAL` when a bar is missing, **never an optimistic value** · **no trade blends environments or
provenances**, and an all-environments listing groups by environment rather than combining.

```text
TradeDetail.payload {
    trade_id                  SafeId        required
    summary                   TradeSummary.payload      required -- EMBEDDED, from the same
                                            snapshot_version
    candidate_ref             Ref           required, kind candidate
    brain_decision_ref        Ref           required, kind brain_decision
    risk_decision_ref         Ref           required, kind risk_decision
    order_refs                RefList       required, kind order
    fill_refs                 RefList       required, kind fill
    protection_refs           RefList       required, kind protection
    add_refs                  RefList       required, kind add
    exit_ref                  Ref           conditional, kind exit -- required when CLOSED
    reconciliation_refs       RefList       required, kind reconciliation
    execution_quality_ref     Ref           required, kind execution_quality
    attribution               { strategy: MetricValue, factor: MetricValue,
                                regime: MetricValue, execution: MetricValue,
                                cost: MetricValue, state: enum{PROVISIONAL,FINAL} }
                                            required
    benchmark_movement        MetricValue   required -- unit PERCENT, aligned to the exact
                                            holding-period boundaries used, and stating
                                            PRICE_RETURN or TOTAL_RETURN
    benchmark_series_ref      Ref           required, kind benchmark_series
    lineage                   VersionPins   required
    audit_refs                RefList       required, kind audit_event
    chart_series_ref          Ref           required, kind chart_series -- OHLC with entry,
                                            add, protection and exit markers
    gaps                      [ { expected: ReasonCoded, availability: AvailabilityState,
                                  reason: FieldReasonCode } ]   required -- a missing event
                                            renders as a GAP and never as an inference
}
```

**Identity** `trade_id` · **classification** the strictest of its resolved parts · **scope**
`portfolio:read`, plus each reference's own scope · **invariants** **the join is a read-model
concern**: every downstream fact arrives by reference and **no sizing or execution field is added to
`CandidateIntent`** · a provisional attribution is labelled and finalization is a recorded event ·
**a price-return benchmark is never compared against a total-return portfolio**.

```text
TradeLifecycle.payload {
    trade_id                  SafeId        required
    events                    [ { event_id: SafeId, event_kind: ReasonCoded,
                                  event_time: Instant, observed_time: Instant,
                                  quantity: Quantity, price: MetricValue,
                                  downstream_stage: DownstreamStage,
                                  correction_of: Ref (ZERO_OR_ONE),
                                  source_ref: Ref } ]   required, ordered by event_time
                                            with observed_time retained
    gaps                      [ { between: [Instant, Instant], reason: FieldReasonCode } ]
                                            required
}
```

**Identity** `trade_id` plus `snapshot_version` · **classification** `PRIVATE_OPERATIONAL` ·
**scope** `execution:read` · **invariants** **no broker-native order id is rendered anywhere** ·
ordering is by `event_time`, and a late event **advances no watermark it did not cover** · **a
correction appends a new event referencing the corrected one, and never overwrites it**.

```text
ExecutionQuality.payload {
    scope                     enum{ORDER,FILL,AGGREGATE}   required
    reference_price           { name: ReasonCoded, at: Instant,
                                side_convention: ReasonCoded }   required -- NAMED, always
    slippage                  MetricValue   required -- unit BPS, signed, against the named
                                            reference. Actual fills already incorporate
                                            spread and realized slippage, so no spread or
                                            slippage estimate is subtracted from them again
    fill_rate                 MetricValue   required -- unit PERCENT
    signal_to_order_latency   MetricValue   required -- unit SECONDS
    order_to_fill_latency     MetricValue   required -- unit SECONDS
    clock_source              ReasonCoded   required
    clock_accuracy            MetricValue   required -- unit SECONDS
    aggregation_method        ReasonCoded   conditional -- required when scope is AGGREGATE
}
```

**Identity** the order, fill or aggregate key · **classification** `PRIVATE_OPERATIONAL` · **scope**
`execution:read` · **invariants** slippage without a named reference price, timestamp and side
convention is **not a number this contract admits** · **a modelled cost is never subtracted from an
actual fill that already contains it**, and any comparison stating otherwise names both treatments.

```text
ReconciliationStatus.payload {
    run_id                    SafeId        required
    as_of                     Instant       required
    result                    ReasonCoded   required
    position_diffs            [ { security_ref: Ref, expected: Quantity,
                                  observed: Quantity } ]   required
    order_diffs               [ { local_ref: Ref, disposition: ReasonCoded } ]   required
    orphans                   CountValue    required
    session_state             ReasonCoded   required
    incident_refs             RefList       required, kind incident
}
```

**Identity** `run_id` · **classification** `PRIVATE_OPERATIONAL` · **scope** `execution:read` ·
**invariants** **no brokerage credential or session exists in any Cockpit path** · broker equity
appearing anywhere in this view is labelled informational · **a past reconciliation always shows its
`as_of`**, because a historical success is not current health.

#### Signals

```text
CandidateFunnel.payload {
    window                    { from: Instant, to: Instant }   required
    brain_axis                [ { state: BrainDecisionState, count: CountValue,
                                  reasons: [ { code: ReasonCoded,
                                               count: CountValue } ] } ]   required
    downstream_axis           [ { stage: DownstreamStage, count: CountValue,
                                  availability: AvailabilityState } ]   required
    conversion                [ { from: ReasonCoded, to: ReasonCoded,
                                  rate: MetricValue } ]   required
}
```

**Identity** the window plus the scope · **classification** `PRIVATE_OPERATIONAL` · **scope**
`signals:read` · **invariants** **the two axes are presented side by side and are never merged** ·
**`READY_FOR_RISK_REVIEW` is not presented as a successful end state** · every downstream member is
`NOT_IMPLEMENTED` in V1.

```text
CandidateSummary.payload {
    candidate_id              SafeId        required
    security_ref              Ref           required, kind evidence
    decided_at                Instant       required
    brain_state               BrainDecisionState        required
    primary_reason            ReasonCoded   required
    conviction_band           ReasonCoded   required
    strategy_module           ReasonCoded   required
    downstream_stage          MetricValue   required -- a DownstreamStage or its availability
    detail_ref                Ref           required, kind candidate
    pins                      VersionPins   required
}
```

**Identity** `candidate_id` · **classification** `PRIVATE_OPERATIONAL` · **scope** `signals:read` ·
**invariants** the eight Brain states render as a closed set · **no share count, dollar amount,
position size, order type or route appears in this payload**.

```text
CandidateDetail.payload {
    candidate_id              SafeId        required
    security_ref              Ref           required, kind evidence
    thesis                    ReasonCoded   required -- closed codes, never free text
    why_now                   ReasonCoded   required
    deterministic_evidence    [ { factor: ReasonCoded, value: MetricValue,
                                  pin: SafeId } ]   required
    ai_evidence_refs          RefList       required, kind evidence -- with model, prompt and
                                            source provenance on each reference
    challenger_objections     RefList       required, kind evidence
    brain_state               BrainDecisionState        required
    blocking_reasons          [ ReasonCoded ]   required
    invalidation_ref          Ref           required, kind evidence -- the technical stop is
                                            a REFERENCE to an invalidation level, and is
                                            never an order
    risk_context              { initial_planned_risk_basis: MetricValue }   required -- the
                                            RISK CONTEXT the Brain may carry, and nothing
                                            downstream of it
    downstream_refs           { risk_decision: Ref, trade: Ref }   required
    pins                      VersionPins   required
}
```

**Identity** `candidate_id` · **classification** `PRIVATE_OPERATIONAL` · **scope** `signals:read` ·
**invariants** **no share count, dollar amount, final position size, broker order type, route,
client order id or broker order id appears anywhere in this payload**, and none is added to
`CandidateIntent` to make a view simpler · **AI evidence never explains a restored candidate**: AI
may remove a candidate and may never restore one, so no `blocking_reasons` entry is ever cleared by
an AI evidence reference.

```text
MissedOpportunity.payload {
    miss_id                   SafeId        required
    candidate_ref             Ref           required, kind candidate
    cause                     ReasonCoded   required
    window                    { from: Instant, to: Instant }   required
    counterfactual            MetricValue   required -- unit USD or PERCENT, and labelled
                                            HYPOTHETICAL
    assumptions               [ ReasonCoded ]   required -- sizing, costs, borrow, slippage
                                            and the protection that would have been in place
    cost_treatment            enum{GROSS,NET_COMMISSIONS,NET_ALL_COSTS}   required
    population                ReasonCoded   conditional -- required before any rate is shown
    price_path_completeness   enum{COMPLETE,PARTIAL,UNKNOWN}   required
}
```

**Identity** `miss_id` · **classification** `PRIVATE_OPERATIONAL` · **scope** `signals:read` ·
**invariants** **favourable movement after a decision is not profit that was available** · an
incomplete path renders `PARTIAL` · **no false-negative rate is reported without a defined
population** · a counterfactual is never placed in a series with realized results.

#### Strategy, risk and market

```text
StrategyPerformance.payload {
    strategy_module           ReasonCoded   required
    alpha_family              ReasonCoded   required
    strategy_version          SafeId        required
    summary                   PerformanceSummary.payload   required -- EMBEDDED, over this
                                            module and version only
    slices                    [ { axis: ReasonCoded, bucket: ReasonCoded,
                                  summary: PerformanceSummary.payload } ]   required
    trade_population          ReasonCoded   required
}
```

**Identity** module plus version · **classification** `PRIVATE_OPERATIONAL` · **scope**
`strategy:read` · **invariants** **every result is attributed to an exact strategy version** ·
modules keep separate attribution and share family context · **no diversification or alpha claim is
carried in this payload**, and none is derivable from it.

```text
StrategyHealth.payload {
    strategy_version          SafeId        required
    state                     StrategyHealthState       required -- the seven ADR-0026 states
    since                     Instant       required
    transitions               [ { from: StrategyHealthState, to: StrategyHealthState,
                                  at: Instant, rule: ReasonCoded, authority: ReasonCoded,
                                  input_refs: RefList } ]   required
    drift                     [ { measure: ReasonCoded, value: MetricValue } ]   required
    failure_clusters          [ { cluster: ReasonCoded, count: CountValue,
                                  evidence_refs: RefList } ]   required
    minimum_observations_met  boolean       required
    queue_item_ref            Ref           conditional, kind queue_item -- required when a
                                            degradation created one
    recovery_authority        ReasonCoded   required -- reduction and disablement of new
                                            entries are automatic; RESTORATION IS NOT, and
                                            recovery past a governed suspension is never
                                            automatic
}
```

**Identity** `strategy_version` · **classification** `PRIVATE_OPERATIONAL` · **scope**
`strategy:read` · **invariants** **only the seven health states render** · **the view causes no
transition** · a degradation shows the research queue entry it created · `recovery_authority` is
displayed unchanged and **is neither strengthened nor widened by this contract**.

```text
StrategyVersion.payload {
    strategy_version          SafeId        required
    module                    ReasonCoded   required
    lifecycle_stage           ReasonCoded   required -- an ADR-0026 lifecycle value
    maturity_stage            MaturityStage required -- the presentation view of it
    created_at                Instant       required
    immutable                 boolean       required
    lineage_refs              RefList       required, kind source_fact
    open_position_refs        RefList       required, kind source_fact
    rollback_of               Ref           conditional, kind strategy_version
}
```

**Identity** `strategy_version` · **classification** `PRIVATE_OPERATIONAL` · **scope**
`strategy:read` · **invariants** production versions render immutable · **open-position pinning is
explicit**, and an open position stays governed by the exact versions that opened it.

```text
MaturityStatus.payload {
    strategy_version          SafeId        required
    maturity_stage            MaturityStage required
    lifecycle_stage           ReasonCoded   required
    runtime_environment       Environment   required
    order_authority           ReasonCoded   required -- SHADOW carries NONE
    outstanding_gates         [ { gate: ReasonCoded, state: ReasonCoded } ]   required
    decision_refs             RefList       required, kind decision
}
```

**Identity** `strategy_version` · **classification** `PUBLIC_SAFE` where every contributing fact is
a tracked governance fact, otherwise `PRIVATE_OPERATIONAL` · **scope** `governance:read` ·
**invariants** **selecting an environment advances no maturity** · the stage-to-lifecycle mapping
matches the architecture extension exactly · **Shadow shows no order authority**.

```text
RiskSnapshot.payload {
    as_of                     Instant       required
    open_planned_risk         RecordValue<CurrentOpenPlannedRisk>   required -- portfolio
                                            aggregate
    initial_planned_risk_open [ { trade_ref: Ref,
                                  value: RecordValue<InitialPlannedRisk> } ]   required
    permitted                 [ RecordValue<PermittedRisk> ]   required
    concentration             MetricValue   required
    exposure_refs             RefList       required, kind source_fact
    portfolio_volatility      MetricValue   required
    gap_event_risk            RecordValue<GapEventRisk>   conditional
    loss_thresholds           [ { threshold: ReasonCoded, value: MetricValue,
                                  policy_ref: PolicyRef } ]   required
    risk_tier                 ReasonCoded   required
    circuit_breaker_state     ReasonCoded   required
    new_entry_state           ReasonCoded   required
    decisions                 [ { decision_ref: Ref, at: Instant,
                                  outcome: ReasonCoded } ]   required
}
```

**Identity** the snapshot instant · **classification** `PRIVATE_OPERATIONAL` · **scope**
`risk:read` · **invariants** **read-only, without exception**: the payload changes no threshold,
trips no breaker and reduces no exposure · every permitted value carries its `PolicyRef` · the
governed research values are **reproduced for context, labelled as research parameters, and changed
nowhere**.

```text
ShortSideSnapshot.payload {
    as_of                     Instant       required
    short_positions           RefList       required, kind source_fact
    borrow                    [ { security_ref: Ref, availability: ReasonCoded,
                                  fee: MetricValue, quantity: MetricValue,
                                  deterioration: MetricValue, record_ref: Ref } ]   required
    crowding                  MetricValue   required
    utilization               MetricValue   required
    squeeze_state             ReasonCoded   required
    ssr_state                 ReasonCoded   required
    recall_risk               ReasonCoded   required
    gross_short               Magnitude     required
    permitted_gross_short     RecordValue<PermittedRisk>   required -- scope GROSS_SHORT
    blocked_shorts            [ { candidate_ref: Ref, reason: ReasonCoded } ]   required
}
```

**Identity** the snapshot instant · **classification** `PRIVATE_OPERATIONAL` · **scope**
`risk:read` · **invariants** **borrow availability is never inferred from price** · an unknown
borrow renders unknown or `BLOCKED_BORROW`, **never as available** · every borrow figure carries the
record reference it came from.

```text
MarketRegime.payload {
    context_version           SafeId        required
    as_of                     Instant       required
    regime                    ReasonCoded   required
    components                [ { component: ReasonCoded, value: MetricValue } ]   required
    stress                    MetricValue   required
    history                   Series        required
    information_profile       enum{PUBLIC_PIT,PROVIDER_REALISTIC_PIT,FORWARD_SYSTEM}
                                            required -- DECLARED, never inferred
}
```

**Identity** `context_version` · **classification** `LICENSED_DERIVED` when any component is derived
from licensed rows, otherwise `PRIVATE_OPERATIONAL` · **scope** `market:read` · **invariants** **the
regime is displayed from a versioned context and never recomputed by a view** · **the view sizes no
exposure** · **no default information profile is invented**.

#### Research and feedback

```text
ResearchRun.payload {
    run_id                    SafeId        required
    registration_ref          Ref           required, kind registration
    challenger_version        SafeId        required
    baseline_ref              Ref           required, kind strategy_version -- a run without
                                            a NAMED baseline renders incomplete
    state                     enum{PLANNED,RUNNING,COMPLETED,FAILED,ABANDONED}   required
    evaluation_class          enum{DETERMINISTIC_REPRODUCTION,EXPLORATORY_REUSE,
                               CONFIRMATORY}   required -- per the feedback specification
                                            §2.7, and NEVER inferred from the state
    dataset_ref               Ref           required, kind evidence -- the locked-set
                                            identity this run touched, where one applies
    counts_against_budget     boolean       required -- true for every terminal state,
                                            including FAILED and ABANDONED
    trial_ordinal             CountValue    required -- read from the registry record
    results                   [ { measure: ReasonCoded, value: MetricValue } ]   required
    decomposition             [ { axis: ReasonCoded, bucket: ReasonCoded,
                                  value: MetricValue } ]   required
    capacity                  MetricValue   required
    stress                    [ { scenario: ReasonCoded, value: MetricValue } ]   required
    reproducibility           { manifest: SafeId, profile: ReasonCoded,
                                revision_view: SafeId, code_identity: SafeId,
                                config_identity: SafeId, seeds: [integer],
                                environment: Environment }   required
    provenance                DataProvenance   required -- BACKTEST_SIMULATED for a research
                                            run, and never placed in a series with realized
                                            results
}
```

**Identity** `run_id` · **classification** `LICENSED_DERIVED` whenever the run consumed licensed
rows, otherwise `PRIVATE_OPERATIONAL` · **scope** `research:read` · **invariants** **every terminal
state counts against the trial budget, failed and abandoned included** · the trial count is read
from the record and never recounted by a view · **synthetic runs are excluded from every real
comparison** · `evaluation_class` is carried, never derived.

```text
ResearchQueueItem.payload {
    item_id                   SafeId        required
    trigger_ref               Ref           required, kind source_fact
    issue                     ReasonCoded   required
    proposed_experiment       ReasonCoded   required
    baseline_ref              Ref           required, kind strategy_version
    state                     enum{QUEUED,PREREGISTRATION_DRAFTED,REGISTERED,WITHDRAWN}
                                            required
    withdrawal_reason         MetricValue   conditional -- required when WITHDRAWN
    awaiting_authorizations   [ ReasonCoded ]   required
    priority                  ReasonCoded   required
}
```

**Identity** `item_id` · **classification** `PRIVATE_OPERATIONAL` · **scope** `research:read` ·
**invariants** **a queue entry is not an authorization**, and every item displays the authorization
it is waiting on · an item with no named baseline is refused at the boundary.

```text
HypothesisRegistration.payload {
    registration_id           SafeId        required
    registered_at             Instant       required
    immutable                 boolean       required -- always true
    trigger_ref               Ref           required, kind queue_item
    strategy_module           ReasonCoded   required
    thesis                    ReasonCoded   required
    baseline_ref              Ref           required, kind strategy_version
    variation                 ReasonCoded   required
    trial_budget              { granted: CountValue, consumed: CountValue,
                                remaining: CountValue }   required
    success_criteria          [ ReasonCoded ]   required
    failure_criteria          [ ReasonCoded ]   required -- NON-EMPTY; a hypothesis that
                                            cannot fail has not been stated
    data_requirements         [ ReasonCoded ]   required
    pins                      { manifest: SafeId, profile: ReasonCoded,
                                revision_view: SafeId, factor_definition_version: SafeId,
                                research_code_identity: SafeId }   required
    lineage                   { parent_registration: Ref (ZERO_OR_ONE),
                                related_registrations: RefList,
                                amendment_chain: RefList,
                                superseded_by: Ref (ZERO_OR_ONE) }   required
    exposure_ledger_ref       Ref           required, kind evidence -- the locked-set
                                            exposure ledger of the feedback specification
                                            §2.7, which spans registrations
    linked_results            RefList       required, kind research_run -- results APPEND and
                                            never edit the registration
}
```

**Identity** `registration_id` · **classification** `PRIVATE_OPERATIONAL` · **scope**
`research:read` · **invariants** **a registration is immutable**; results render as linked appended
records; the amendment chain is visible · **failed and abandoned runs count against the budget** ·
**the trial budget and the exposure ledger are read across the lineage, so a new registration
identity never resets either**.

```text
ChampionChallengerComparison.payload {
    champion_version          SafeId        required
    challenger_version        SafeId        required
    registration_ref          Ref           required, kind registration
    overlap                   [ { measure: ReasonCoded, value: MetricValue } ]   required
    divergence                [ { measure: ReasonCoded, value: MetricValue } ]   required
    exposure_difference       [ { axis: ReasonCoded, value: MetricValue } ]   required
    evidence_completeness     enum{COMPLETE,PARTIAL,UNKNOWN}   required
    readiness                 ReasonCoded   required -- DISPLAYED, never conferred
    data_exposure_disclosure  [ ReasonCoded ]   required -- the disclosures §2.7 requires
}
```

**Identity** the version pair plus the registration · **classification** `PRIVATE_OPERATIONAL` ·
**scope** `research:read` · **invariants** **readiness is displayed and never conferred** · **no
promotion path exists from this view** · a Challenger that outperforms is a Challenger that
outperforms.

```text
AiContribution.payload {
    experiment_ref            Ref           required, kind registration
    arms                      [ { arm: ReasonCoded, population: CountValue,
                                  outcome: MetricValue, uncertainty: MetricValue } ]
                                            required
    matched                   boolean       required
    ai_provenance             { model_version: SafeId, prompt_version: SafeId,
                                source_refs: RefList }   required
    outages                   [ { from: Instant, to: Instant,
                                  handling: ReasonCoded } ]   required
    minimum_observations_met  boolean       required
}
```

**Identity** the experiment plus the arm set · **classification** `PRIVATE_OPERATIONAL` · **scope**
`research:read` · **invariants** **no causal alpha claim is carried** · small populations render
`INSUFFICIENT_OBSERVATIONS` · every AI output carries model version, prompt version and timestamped
source provenance.

```text
FeedbackPipeline.payload {
    stages                    [ { stage: ReasonCoded, item_count: CountValue,
                                  blocked_count: CountValue,
                                  awaiting_authorizations: [ReasonCoded],
                                  item_refs: RefList } ]   required -- one entry per stage
                                            of the ten-stage loop
    human_only_stage          ReasonCoded   required -- the tenth, and it is a person
}
```

**Identity** the pipeline snapshot · **classification** `PRIVATE_OPERATIONAL` · **scope**
`research:read` · **invariants** **no stage advances from this screen** · each stage shows the
authorization it awaits · the tenth stage is displayed and never originated here.

#### Governance

```text
GovernancePacket.payload {
    packet_id                 SafeId        required
    registration_ref          Ref           required, kind registration
    run_refs                  RefList       required, kind research_run
    shadow_refs               RefList       required, kind research_run
    comparison_ref            Ref           required, kind source_fact
    proposal                  ReasonCoded   required
    cause                     ReasonCoded   required
    evidence_refs             RefList       required, kind evidence
    risk_impact               [ { axis: ReasonCoded, value: MetricValue } ]   required
    operational_impact        [ { axis: ReasonCoded, value: MetricValue } ]   required
    failure_modes             [ ReasonCoded ]   required
    recommendation            ReasonCoded   required -- INPUT to a human decision, never the
                                            decision
    trial_count               CountValue    required -- read from the registry
    exposure_disclosure       [ ReasonCoded ]   required -- every reuse the evidence rests on
    state                     enum{ASSEMBLING,READY_FOR_HUMAN_REVIEW}   required
    decision_ref              Ref           conditional, kind decision -- present once a
                                            human decision has been recorded elsewhere
}
```

**Identity** `packet_id` · **classification** `PRIVATE_OPERATIONAL` · **scope** `governance:read` ·
**invariants** **read-only; no approve or reject control exists** · **`READY_FOR_HUMAN_REVIEW` is
not an approval** · a packet with incomplete evidence, an unrecorded trial count, no baseline
comparison or unevaluated criteria is refused rather than assembled.

```text
DecisionRecord.payload {
    decision_id               SafeId        required
    packet_ref                Ref           required, kind packet
    outcome                   enum{APPROVED,REJECTED,MORE_EVIDENCE_REQUESTED}   required
    authority                 ReasonCoded   required
    decided_at                Instant       required
    reasoning_ref             Ref           required, kind evidence
    affected_versions         RefList       required, kind strategy_version
    immutable                 boolean       required -- always true
}
```

**Identity** `decision_id` · **classification** `PRIVATE_OPERATIONAL` · **scope**
`governance:read` · **invariants** **the Cockpit displays this decision and does not originate it in
V1** · the authoritative record stays with the separately governed decision path that owns it.

```text
QualificationStatus.payload {
    facts                     [ { fact_id: SafeId, subject: ReasonCoded,
                                  state: ReasonCoded, as_of: DateOnly,
                                  source_ref: Ref } ]   required -- each fact read
                                            INDEPENDENTLY from tracked repository authority
    gates                     [ { gate: enum{G1,G2,G3,G4,G5,G6,G7},
                                  state: enum{OPEN,CLOSED}, scope: ReasonCoded,
                                  source_ref: Ref } ]   required -- each gate read on its
                                            own, and no blanket statement over all seven
    adr_states                [ { adr: SafeId, state: ReasonCoded,
                                  source_ref: Ref } ]   required
    provider_tests            [ { test: ReasonCoded,
                                  state: enum{UNEVALUATED} } ]   required -- P1 to P9, and
                                            UNEVALUATED is the only state this payload can
                                            carry today
    run_authorizations        [ { run: ReasonCoded, authorization: ReasonCoded,
                                  date_gate: MetricValue } ]   required -- authorization and
                                            date eligibility are TWO SEPARATE FACTS
    phase_state               ReasonCoded   required
    live_trading              ReasonCoded   required -- HARD-DISABLED
}
```

**Identity** the repository revision the facts were read from.
**Provenance and classification** provenance is `REPOSITORY_TRACKED`; classification is
`PUBLIC_SAFE`. **These are real facts and are never relabelled `SYNTHETIC`** — see §7.1 for the
publication rule that admits them, and note that the label alone authorizes no publication.
**Scope** `governance:read`.
**Invariants** every fact carries the tracked source it was read from · **each gate is read
independently** · **P1 to P9 render `UNEVALUATED`** · **Run B authorization and its date gate render
as two separate facts**, and passing a date authorizes nothing · **no private qualification
evidence, locator, record, payload, report, execution identifier, object key or digest ever enters
this payload**.

#### Data, operations and audit

```text
DataQuality.payload {
    subject                   ReasonCoded   required
    information_profile       enum{PUBLIC_PIT,PROVIDER_REALISTIC_PIT,FORWARD_SYSTEM}
                                            required -- declared, never inferred
    coverage                  { present: CountValue, requested: CountValue }   required
    freshness                 FreshnessReport   required -- §3.1: per required
                                            input, with source age and projection
                                            lag reported separately
    lineage_refs              RefList       required, kind source_fact
    quality_checks            [ { check: ReasonCoded, result: ReasonCoded,
                                  as_of: Instant } ]   required
    incident_refs             RefList       required, kind incident
}
```

**Identity** the subject plus the as-of · **classification** `PRIVATE_OPERATIONAL`, or
`LICENSED_DERIVED` where a check result is reconstructable from licensed rows · **scope**
`system:read` · **invariants** **only the three existing profiles render and no default profile is
invented** · **Sharadar price data never renders as `PUBLIC_PIT`**.

```text
SystemJob.payload {
    job_id                    SafeId        required
    kind                      ReasonCoded   required
    last_run                  { at: Instant, outcome: ReasonCoded }   required
    last_success              MetricValue   required -- carries its own as_of
    duration                  MetricValue   required -- unit SECONDS
    queue_depth               CountValue    required
    next_scheduled            MetricValue   required
}
```

**Identity** `job_id` · **classification** `PRIVATE_OPERATIONAL` · **scope** `system:read` ·
**invariants** **displaying jobs does not run them**: there is no start, stop, retry or trigger
control, **and no handler and no control API route exists** · **last success carries its as-of
time**.

```text
SystemIncident.payload {
    incident_id               SafeId        required
    opened_at                 Instant       required
    closed_at                 MetricValue   required
    severity                  ReasonCoded   required
    subject                   ReasonCoded   required
    evidence_refs             RefList       required, kind source_fact
    state                     ReasonCoded   required
}
```

**Identity** `incident_id` · **classification** `PRIVATE_OPERATIONAL` · **scope** `system:read` ·
**invariants** an open incident count is `EMPTY_VERIFIED` when the producer ran and found none, and
**`NOT_IMPLEMENTED` when it did not run at all**.

```text
Alert.payload {
    alert_id                  SafeId        required
    condition                 ReasonCoded   required
    severity                  ReasonCoded   required
    dedup_key                 SafeId        required
    first_seen                Instant       required
    last_seen                 Instant       required
    occurrence_count          CountValue    required
    state                     enum{OPEN,RESOLVED}   required
    evidence_refs             RefList       required, kind source_fact
}
```

**Identity** `dedup_key` · **classification** the strictest of its evidence · **scope**
`system:read` · **invariants** **one condition produces one alert with an occurrence count** ·
**no external notification integration exists**.

```text
AuditEvent.payload {
    event_id                  SafeId        required
    event_kind                ReasonCoded   required
    event_time                Instant       required
    observed_time             Instant       required
    actor                     ReasonCoded   required
    subject_refs              RefList       required, kind source_fact -- CLASSIFIED
                                            REFERENCES, never payload copies
    lineage                   VersionPins   required
    record_digest             SafeId        required -- a digest of KALPAMANI's OWN record,
                                            never of a vendor payload
    supersedes                Ref           conditional, kind audit_event -- present on a
                                            correction event
    tombstone_of              Ref           conditional, kind audit_event -- present on a
                                            deletion event
    deletion_authority        ReasonCoded   conditional -- required on a tombstone event
}
```

**Identity** `event_id` · **classification** `PRIVATE_OPERATIONAL` · **scope** `audit:read` ·
**invariants** **no licensed content, vendor row or reconstructable derivative appears in an audit
payload** · **a correction or deletion appends a new linked event and the original event is never
mutated** · the projection is rebuildable and separately identified from its source events, and a
rebuild **never mutates a source event**.

#### Search and assistant

```text
SearchResultPage.payload {
    query_echo                ReasonCoded   required -- the parsed, typed query, never the
                                            raw string
    results                   [ { ref: Ref, title: ReasonCoded, subject: ReasonCoded,
                                  environment: Environment, provenance: DataProvenance,
                                  classification: DataClassification } ]   required
    scoping                   { environment: Environment, provenance: DataProvenance }
                                            required -- present on every result and never
                                            widened server-side
    grouped_by_environment    boolean       required -- always true
}
```

**Identity** the query plus the scope · **classification** the strictest result's · **scope** the
union of the scopes the caller holds, and **nothing outside them is listed** · **invariants** **no
state-changing verb exists** · **an all-environments search never implies a combined result** and
groups by environment instead · a result the caller may not read is omitted, not teased.

```text
AskAnswer.payload {
    question_class            ReasonCoded   required -- a typed, bounded analytical class,
                                            never arbitrary SQL or code
    answer                    MetricValue   required
    citations                 RefList       required, kind source_fact -- ONE_OR_MORE, or
                                            the answer is not returned
    abstained                 boolean       required
    abstention_reason         MetricValue   conditional -- required when abstained
    scanned_extent            CountValue    required -- against the endpoint's declared
                                            maximum
}
```

**Identity** the question class plus the scope · **classification** `PUBLIC_SAFE` only when every
citation is · **scope** the union of the caller's read scopes · **invariants** **no arbitrary SQL or
code execution, no unrestricted data access, no state mutation, no broker action, and no external
LLM transmission of licensed data** · **abstention over invention**: an answer with no citation is
not returned · an `UNCLASSIFIED` payload **fails closed** rather than being sent.

---

### 4.6 Synthetic and unavailable examples

**Two shared templates, and every example in the Cockpit package uses one of them.** An example that
invents its own shape is a second contract.

```text
SYNTHETIC EXAMPLE TEMPLATE
    provenance        SYNTHETIC              -- unmissable, at page and component level
    environment       RESEARCH
    entity_id         a deterministic fixture id, from a repository-owned fixture
    values            deterministic, repository-owned, and derived from NO vendor row,
                      NO broker record and NO owner private data
    labelling         every rendered figure carries the SYNTHETIC badge
    meaning           a shape a screen would take. NOT a result, NOT evidence, and NOT a
                      threshold -- no numerical research or safety threshold becomes a
                      production rule because it appears in an example

UNAVAILABLE EXAMPLE TEMPLATE
    availability      the exact AvailabilityState, from §2.1
    reason            the exact FieldReasonCode, from §4.1, and a pairing the
                      §4.1.1 matrix permits -- never a state written where a
                      reason belongs, and never the reverse
    value             ABSENT -- never zero, never healthy, never passed, never no incidents
    a record          ABSENT inside its RecordValue wrapper -- never a skeleton
                      carrying invented times, policy ids or zeroed money
    an AVAILABLE one  carries reason NONE. A good value never wears a failure
                      reason to satisfy a required field
    as_of             present when a prior value existed, so a reader can see how old it is
    meaning           EMPTY_VERIFIED and NOT_YET_AVAILABLE look identical on a naive screen
                      and mean opposite things, so both are rendered distinctly
```

**Every example in this package is one of these two.** A read model whose producer does not exist is
demonstrated with the unavailable template for its real state and the synthetic template for its
shape, and **the two are never blended into one figure**.

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

### 5.1 The per-endpoint contract

**Every endpoint states seven things**, and an endpoint missing any of them is not implementable
from this document. `single` means one envelope; `page` means a cursor-paginated collection;
`series` means one envelope carrying a `Series`.

**The page-size and extent numbers below are proposed read-resource limits.** They bound a read
API's work and its response size. **They are not trading risk limits, position limits, capital
limits or any other governed value**, and adopting one here adopts nothing anywhere else.

| Endpoint | Response | Filters | Sorts | Page size (default / max) | Extent bound |
|---|---|---|---|---|---|
| `/executive/overview` | `ExecutiveOverview` single | environment, as_of | — | — | one snapshot |
| `/executive/attention` | `AttentionItem` page | severity, subject, state | materiality_rank, last_seen | 25 / 100 | 500 items |
| `/executive/what-changed` | `WhatChangedEntry` page | subject, change_kind, window | event_time, materiality | 25 / 100 | 31 days |
| `/portfolio/performance` | `PerformanceSeries` + `PerformanceSummary` series | window, granularity, cost_treatment, benchmark | — | — | 3,650 daily points |
| `/portfolio/positions` | `PositionSnapshot` page | direction, sector, strategy, borrow_state | quantity, unrealized, holding_duration | 50 / 200 | one snapshot |
| `/portfolio/exposure` | `ExposureAggregate` page | grouping, direction | gross, net, bucket | 50 / 200 | one snapshot |
| `/portfolio/trades` | `TradeSummary` page | window, direction, trade_status, strategy, outcome | entry_time, exit_time, r_multiple, realized_pnl | 50 / 200 | 10,000 trades |
| `/portfolio/trades/{trade_id}` | `TradeDetail` single | — | — | — | one trade |
| `/portfolio/trades/{trade_id}/lifecycle` | `TradeLifecycle` page | event_kind | event_time | 100 / 500 | 5,000 events |
| `/strategy/performance` | `StrategyPerformance` page | module, family, version, window, slice_axis | total_return, expectancy, trade_count | 25 / 100 | 200 versions |
| `/strategy/health` | `StrategyHealth` page | state, module, version | since, state | 25 / 100 | 200 versions |
| `/strategy/versions` | `StrategyVersion` page | module, lifecycle_stage, maturity_stage | created_at | 50 / 200 | 2,000 versions |
| `/strategy/champion-challenger` | `ChampionChallengerComparison` page | champion, challenger, registration | overlap, divergence | 25 / 100 | 200 pairs |
| `/signals/funnel` | `CandidateFunnel` single | window, module, environment | — | — | 90 days |
| `/signals/candidates` | `CandidateSummary` page | window, brain_state, module, security | decided_at, conviction_band | 50 / 200 | 20,000 candidates |
| `/signals/candidates/{candidate_id}` | `CandidateDetail` single | — | — | — | one candidate |
| `/signals/missed` | `MissedOpportunity` page | window, cause, module | window_start, counterfactual | 25 / 100 | 5,000 items |
| `/risk/snapshot` | `RiskSnapshot` single | as_of | — | — | one snapshot |
| `/risk/short-side` | `ShortSideSnapshot` single | as_of | — | — | one snapshot |
| `/market/regime` | `MarketRegime` single + series | as_of, window | — | — | 3,650 daily points |
| `/execution/quality` | `ExecutionQuality` page | window, scope, module | slippage, latency | 50 / 200 | 50,000 fills |
| `/execution/reconciliation` | `ReconciliationStatus` page | window, result | as_of | 25 / 100 | 365 days |
| `/research/runs` | `ResearchRun` page | registration, state, evaluation_class, window | started_at, trial_ordinal | 25 / 100 | 5,000 runs |
| `/research/queue` | `ResearchQueueItem` page | state, priority, trigger | priority, created_at | 25 / 100 | 1,000 items |
| `/research/hypotheses` | `HypothesisRegistration` page | module, state, window | registered_at | 25 / 100 | 2,000 registrations |
| `/research/ai-contribution` | `AiContribution` page | experiment, window | outcome | 25 / 100 | 200 experiments |
| `/research/feedback-pipeline` | `FeedbackPipeline` single | environment | — | — | one snapshot |
| `/governance/packets` | `GovernancePacket` page | state, module | assembled_at | 25 / 100 | 1,000 packets |
| `/governance/decisions` | `DecisionRecord` page | outcome, window | decided_at | 25 / 100 | 5,000 decisions |
| `/governance/qualification` | `QualificationStatus` single | as_of | — | — | one repository revision |
| `/governance/maturity` | `MaturityStatus` page | maturity_stage, module | stage | 50 / 200 | 2,000 versions |
| `/system/data-quality` | `DataQuality` page | subject, profile, window | as_of, coverage | 50 / 200 | 365 days |
| `/system/jobs` | `SystemJob` page | kind, outcome | last_run | 50 / 200 | 1,000 jobs |
| `/system/incidents` | `SystemIncident` page | severity, state, window | opened_at | 25 / 100 | 5,000 incidents |
| `/system/alerts` | `Alert` page | severity, state, window | last_seen, severity | 50 / 200 | 10,000 alerts |
| `/audit/events` | `AuditEvent` page | event_kind, actor, subject, window | event_time | 100 / 500 | 90 days per request |
| `/search` | `SearchResultPage` page | subject, environment, provenance | relevance, event_time | 25 / 100 | 20 read models |
| `/ask` | `AskAnswer` single | question_class, window, environment | — | — | 100,000 scanned rows |

**Where a bound must come from a separately governed policy, it is a reference and not a number.**
An endpoint whose extent, retention or scope is set by such a policy carries the `PolicyRef`, and
**a request whose governing policy reference is absent is refused with `POLICY_REFERENCE_MISSING`**
rather than served under a default nobody approved.

### 5.2 Cursor, snapshot and error semantics

| | |
|---|---|
| **cursor** | opaque, and it encodes the projection `snapshot_version`, the sort key, the tiebreak key and the full filter set. **A cursor is never a row offset**, and a cursor from one filter set is refused against another |
| **snapshot pinning** | a page continues against the snapshot its cursor names. If that snapshot has been superseded, the response is `PARTIAL` with `UPSTREAM_INPUT_STALE` and names the current snapshot — **it never silently continues across two snapshots** |
| **stable ordering** | every sort has a declared deterministic tiebreak, so two identical requests return identical order |
| **errors** | a closed error vocabulary, and **no free text**: `UNKNOWN_SCHEMA_VERSION`, `UNKNOWN_API_VERSION`, `UNKNOWN_FILTER`, `UNKNOWN_SORT`, `PAGE_SIZE_EXCEEDED`, `EXTENT_EXCEEDED`, `CURSOR_INVALID`, `CURSOR_SNAPSHOT_SUPERSEDED`, `SCOPE_MISSING`, `SCOPE_INSUFFICIENT`, `CLASSIFICATION_WITHHELD`, `POLICY_REFERENCE_MISSING`, `PROJECTION_ERROR` |
| **refusal, not truncation** | `PAGE_SIZE_EXCEEDED` and `EXTENT_EXCEEDED` are refusals. **A silently truncated result is a wrong answer wearing a correct one's shape** |
| **no error carries data** | an error response carries the envelope and the closed code, and **never a partial payload, a bucket name, a key, an identifier or a backend message** |

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
| **freshness is data, not policy** | a cached response carries the same `freshness` report and `as_of_time` the origin produced, **and the origin's `evaluation_time` with them**, so a consumer reads a `source_age` as of when it was computed rather than as of now. A cache never makes a stale value look fresh, and **never freezes an `AVAILABLE` state while the source ages** — an entry lives at most as long as the strictest `contract_max_age` it carries (§3.1) |

### 7.1 Classification is a label; publication is a gate

**These are two different questions, and collapsing them is how a payload reaches a public host
because someone marked it safe.**

| | |
|---|---|
| **classification** | *how sensitive is this content?* It is a **sensitivity label** on a payload, and it is the answer to ADR-0007's question: **can vendor rows be recovered from this artifact? Yes or uncertain means licensed** |
| **publication** | *may this content leave its boundary, to this host, now?* It is an **authorization**, recorded, with an authority and a time |

**A `PUBLIC_SAFE` label does not authorize publication.** It says the content would not disclose
licensed rows, private operational state or an identifier; it does not say anyone approved putting
it on an externally hosted deployment. **Publication to `PUBLIC_EDGE` requires a recorded release
authorization in addition to the label**, and a payload whose classification is right and whose
release authorization is missing is **refused, not published**.

**What may be displayed on `PUBLIC_EDGE`, exactly.**

| Provenance | Read models | Condition |
|---|---|---|
| `SYNTHETIC` | any read model | the fixture is repository-owned and deterministic, and every figure carries the `SYNTHETIC` badge |
| `REPOSITORY_TRACKED` | `QualificationStatus`; the governance-derived entries of `AttentionItem`, `WhatChangedEntry`, `SearchResultPage` and `MaturityStatus` | every fact resolves to a **tracked source already published in this public repository**, and a recorded release authorization covers the deployment |

**Nothing else, and no other provenance.** A read model not in that table is not published to
`PUBLIC_EDGE` at any classification, and **a real fact is never relabelled `SYNTHETIC` to get
there** — the two provenances are rendered distinctly, side by side, on the same page.

**Uncertain classification fails closed.** `UNCLASSIFIED` goes nowhere. A payload whose
classification cannot be determined is treated as `LICENSED_DERIVED` for the purpose of every
boundary decision, and it is **refused rather than downgraded**.

**A private projection may legitimately be licensed-derived.** A qualified, authorized private price
projection is `LICENSED_DERIVED`, lives inside the approved private deployment boundary, and is a
correct and useful read model there. **Licensed-derived is not a defect; publishing it is.** What
the classification forbids is public Git, an external LLM, third-party hosting, an external cache,
telemetry, a build artifact and an ordinary log line — never its existence inside the boundary that
already holds the rows it came from.

**CONTROL publication remains DEFERRED**, and a `CONTROL` payload is refused at admission
regardless of host, label, authorization or scope.

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
| one contributing input failed | envelope `availability = PARTIAL`, the failing component named by a closed code, the rest served. **The composite takes the worst state any required input reached** (§3.1), and one healthy input never raises it |
| a whole view failed | `availability = ERROR`, with a closed reason code and no fabricated payload |
| an input is not implemented | `NOT_IMPLEMENTED`, distinctly from `EMPTY_VERIFIED` |
| an input exists but may not run | `NOT_AUTHORIZED`, distinctly from `NOT_IMPLEMENTED` |
| too few observations | `INSUFFICIENT_OBSERVATIONS` with `BELOW_MINIMUM_OBSERVATIONS`, and **no ratio is returned** |

**A composite view reports the availability of each contributing part**, so an executive tile can be
`AVAILABLE` while the page around it is `PARTIAL`, and the reader can see which is which. **No
partial failure is rounded up to success.**

---

## 10. Identifiers, redaction and access control

**Only safe internal identifiers cross the boundary.** Two lists, and they are governed
differently: one is an absolute prohibition, the other is a classification rule. **Collapsing them
is how a legitimate private projection gets refused and an infrastructure identifier gets
rationalised.**

**List A — credentials and infrastructure identifiers.** **Never** placed in a read model, a URL, a
cache key, an export, a log line or a chart label — **at any classification, in any environment, on
any host, under any authorization**. There is no boundary inside which these become acceptable read
content.

```text
brokerage account identifier        account-binding digest
broker-native order id (BrokerId)   credential or token of any kind
AWS account id or ARN               bucket name
secret identifier                   execution identifier or locator key
private filesystem path             owner personal identifier
SSO start URL                       IAM role or permission-set name
private qualification locator key   private report key or object key
```

**List B — classified payload content.** A **vendor row**, and any reconstructable derivative of
one, is not forbidden content: it is **classified** content, and its classification decides where it
may live.

| | |
|---|---|
| **inside the approved private deployment boundary** | a read model derived from licensed rows is `LICENSED_DERIVED`, and it is **legitimate there**. A qualified, authorized private price projection is exactly this |
| **`PUBLIC_SAFE` and `PRIVATE_OPERATIONAL` payloads** | carry **no** vendor row and **no** reconstructable derivative. A payload that would carry one is `LICENSED_DERIVED` by definition, and mislabelling it does not change what it contains |
| **outside the boundary** | never — not in public Git, not in an external LLM prompt, not on third-party hosting, not in an external cache or CDN, not in telemetry, not in a build artifact, and not in an ordinary log line |
| **uncertain** | treated as `LICENSED_DERIVED` and **refused rather than downgraded**. *Yes or uncertain means licensed*, exactly as ADR-0007 already asks it |

**The classification is a sensitivity label and not a publication permission** — §7.1 holds the
publication gate, and a correct label never substitutes for the release authorization it requires.

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

**An audit event carries permitted evidence and references, never a copy of deletable licensed
content.** That is the whole reconciliation: the immutable side holds what stays, and the deletable
side holds what goes.

**Deletion and correction append; they never mutate.** An audit event, once written, is not edited,
redacted in place, restated or overwritten — including by a deletion.

| Situation | What happens |
|---|---|
| **a correction** | a **new** audit event is appended, carrying `supersedes` pointing at the event it corrects. **Both events remain**, and the read model exposes that a correction occurred |
| **referenced licensed content is deleted** | a **new** tombstone event is appended, carrying `tombstone_of` and its recorded `deletion_authority`. The original event is unchanged; the reference it carries now resolves to a deleted state rather than to content |
| **the governance meaning** | survives in full. **The governance evidence is preserved; the vendor data is not retained** |
| **a projection that cached licensed content** | is rebuilt without it, and **the rebuild is itself recorded**. A rebuild never mutates a source event |

**Authorized cached copies carry the deletion obligation with them.** Wherever an authorized copy of
licensed-derived content exists — a projection row, a materialized view, an operational cache — it
is enumerable, it lives inside the approved private boundary, and it is **subject to the same
destruction obligation as its source**. **This document states that obligation and implements no
deletion**: the deletion path, its authority and its runbook stay where they already are, and
nothing here grants operational authority to delete, retain or copy anything.

**The tombstone is a governance record, not a discovery mechanism.** Deletion must never depend on
an audit event, a projection or a locator to find licensed objects — prefix-based deletion is
unchanged, and an absent reference is not evidence that nothing exists.

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
| **missingness** | a missing input yields an availability state **and its reason code**, never a zero, and never a state borrowed from the reason vocabulary |
| **minimum observations** | every metric declares one and returns `INSUFFICIENT_OBSERVATIONS` with `BELOW_MINIMUM_OBSERVATIONS` below it |

### 12.2 Metric identity

**Every metric has a stable `metric_id`**, and every `MetricValue` carries it alongside the
`metric_definition_version` it was computed under. **A number with no `metric_id` is not a metric**,
and two values with the same `metric_id` and different `metric_definition_version` are **never
compared without both versions displayed**.

### 12.3 The metrics

**Each row states its formula or its unambiguous rule, its unit, its denominator, its calendar and
timezone basis, its cost treatment, its sign convention, its sample convention, its minimum
observations and what it returns when it cannot be computed.** A metric may state `n/a` for a
dimension that genuinely does not apply to it — that is a statement, not an omission.

| `metric_id` | Formula or rule | Unit · denominator | Basis | Minimum obs. | Unavailable outcome — **state, then reason** |
|---|---|---|---|---|---|
| `pnl.realized` | sum of closed-portion proceeds minus closed-portion cost basis, weighted by filled quantity at each stage | USD · n/a | trade dates on the named calendar, UTC storage | 0 | `NOT_YET_AVAILABLE` if no closed portion exists |
| `pnl.unrealized` | open quantity × (mark − position-weighted basis), signed | USD · n/a | mark as-of, named source | 0 | `NOT_YET_AVAILABLE` with `UPSTREAM_INPUT_MISSING` when the mark is absent — **never zero** |
| `pnl.combined` | `pnl.realized + pnl.unrealized`, **labelled combined and never presented as realized** | USD · n/a | as above | 0 | `PARTIAL` when either component is |
| `return.time_weighted` | chain-link sub-period returns across every external cash-flow boundary: `∏(1 + r_i) − 1`, where each `r_i` spans a flow-free sub-period. **A flow-free period is one sub-period and is a complete, valid time-weighted return** — the chaining exists to survive flows, not to require them | RATIO · chained sub-period beginning values | daily on the named calendar, UTC | **1 sub-period**, each sub-period requiring a beginning and an ending valuation | `INSUFFICIENT_OBSERVATIONS` with `BELOW_MINIMUM_OBSERVATIONS` when no complete sub-period exists; `NOT_APPLICABLE` with `DENOMINATOR_ZERO` when a sub-period's beginning value is zero |
| `return.money_weighted` | internal rate of return over the dated external cash flows and the terminal value | RATIO · dated flows | as above | 2 flows | `INSUFFICIENT_OBSERVATIONS`; only returned when explicitly requested, always labelled |
| `return.naive` | **not defined, and not offered.** Begin/end division across a period containing a cash flow is refused at the boundary | — | — | — | refused |
| `cashflow.external` | deposits and withdrawals, dated and signed | USD · n/a | flow dates | 0 | `NOT_YET_AVAILABLE` |
| `drawdown.current` | `equity / running_peak − 1` on the named equity series, after cash-flow adjustment | RATIO · running peak | series frequency and basis named | 2 points | `PARTIAL` on a gapped series |
| `drawdown.max` | the minimum of `drawdown.current` over the stated window | RATIO · running peak | window, frequency and `CLOSE_ONLY` or `INTRADAY` all named | 2 points | `PARTIAL` |
| `exposure.long` · `.short` · `.gross` · `.net` | signed position values aggregated against a named base; short reported as a **positive magnitude with `direction = SHORT`** | USD or PERCENT · the named base | snapshot as-of | 0 | `NOT_YET_AVAILABLE` with `UPSTREAM_INPUT_MISSING` |
| `risk.initial_planned` | the immutable entry-time risk record: `shares_filled_at_entry × abs(entry_reference_price − entry_invalidation_level)` | USD and PERCENT · strategy capital **at entry** | recorded at entry | 0 | `NOT_YET_AVAILABLE` with `UPSTREAM_INPUT_MISSING`, or `NOT_IMPLEMENTED` with `PRODUCER_NOT_IMPLEMENTED` — **whichever is true, and never `NOT_APPLICABLE`** |
| `risk.open_planned` | the risk engine's assessment of the **remaining** exposure, as of its own instant | USD and PERCENT · strategy capital **as of** | assessment as-of, always displayed | 0 | `STALE` with `UPSTREAM_INPUT_STALE` past its contract; `NOT_YET_AVAILABLE` with `UPSTREAM_INPUT_MISSING` when absent |
| `risk.permitted` | a separately governed policy value, carried with its `PolicyRef` | USD and PERCENT · the policy's own base | policy version and as-of | 0 | `NOT_YET_AVAILABLE` with `POLICY_REFERENCE_MISSING` |
| `expectancy.currency` | `Σ outcome / n` over the **defined** closed-trade population | USD · trade count | trade dates | 30 trades | `INSUFFICIENT_OBSERVATIONS` with `BELOW_MINIMUM_OBSERVATIONS` |
| `expectancy.r` | `Σ r_multiple / n` over the same population | R_MULTIPLE · trade count | trade dates | 30 trades | `INSUFFICIENT_OBSERVATIONS` with `BELOW_MINIMUM_OBSERVATIONS`; refused for any trade lacking `risk.initial_planned` |
| `profit_factor` | `gross_profit / gross_loss`, both from closed trades, both under one stated cost treatment | RATIO · gross loss | trade dates | 20 trades | `NOT_APPLICABLE` with `DENOMINATOR_ZERO` when gross loss is zero — **never infinity, never a sentinel, never a large number** |
| `win_rate` | `winners / population`, where the population is defined and **break-even trades are counted in a stated bucket** | RATIO · defined population | trade dates | 20 trades | `INSUFFICIENT_OBSERVATIONS` with `BELOW_MINIMUM_OBSERVATIONS` |
| `sharpe` | `(mean(r) − rf) / stdev(r) × √A`, with `r` at the stated frequency, `rf` the stated risk-free assumption, `A` the stated annualization factor and `stdev` the stated **sample** convention | DIMENSIONLESS · standard deviation of `r` | frequency, calendar and timezone named | 60 periods | `INSUFFICIENT_OBSERVATIONS` — **a Sharpe from twelve observations is decoration** |
| `r_multiple` | `realized_and_unrealized_outcome / risk.initial_planned` | R_MULTIPLE · **initial** planned risk | fixed at entry | 0 | `NOT_YET_AVAILABLE` with `UPSTREAM_INPUT_MISSING` when initial planned risk is absent; `NOT_APPLICABLE` with `NOT_DEFINED_FOR_SUBJECT` **only** when the trade never opened; `NOT_APPLICABLE` with `DENOMINATOR_ZERO` when the recorded initial planned risk is zero |
| `holding_period` | exit-or-`as_of` minus entry, on the stated calendar, stating **calendar or trading days** | TRADING_DAYS or CALENDAR_DAYS · n/a | named calendar | 0 | an open trade reports elapsed-to-`as_of`, **labelled open** |
| `mfe` | `max(favourable excursion from entry)` over the holding period, on the stated bar frequency and price basis | USD **and** R_MULTIPLE, both offered, never mixed in one value · entry reference | bar frequency and basis named | 1 bar | `PARTIAL` on any missing bar — **never an optimistic value** |
| `mae` | `max(adverse excursion from entry)`, same frequency and basis as `mfe` | as `mfe` | as `mfe` | 1 bar | `PARTIAL` |
| `capture_ratio` | `realized_outcome / mfe`, **both in the same unit and on the same bar frequency and basis** | RATIO · MFE | as `mfe` | 1 bar | `NOT_APPLICABLE` with `DENOMINATOR_ZERO` when MFE is zero or negative |
| `slippage` | `side_sign × (fill_price − reference_price) / reference_price × 10,000`, against a **named** reference price carrying its own timestamp. `side_sign` is **+1 for every buy** — buy-to-open and buy-to-cover — and **−1 for every sell** — sell-to-close and sell-to-open. **Positive is adverse cost; negative is a favourable fill.** §12.3.1 works the arithmetic through | BPS · reference price | fill timestamps, clock source named | 1 fill | `NOT_YET_AVAILABLE` with `UPSTREAM_INPUT_MISSING` when the reference is absent; `NOT_APPLICABLE` with `DENOMINATOR_ZERO` when the reference price is zero |
| `slippage.aggregate` | the per-fill values combined by a **named** aggregation method, **quantity-weighted by default**: `Σ(bps_i × qty_i) / Σ qty_i` over fills that each have a resolvable reference. **Fills with no reference are excluded and counted**, and the result is `PARTIAL` naming how many — an average over a silently reduced population is a different metric | BPS · reference price | as above | 20 fills | `INSUFFICIENT_OBSERVATIONS` with `BELOW_MINIMUM_OBSERVATIONS`; `NOT_APPLICABLE` with `DENOMINATOR_ZERO` when total weight is zero |
| `latency.signal_to_order` | `order_submitted_at − signal_at`, from recorded timestamps | SECONDS · n/a | clock source and accuracy stated | 1 | `NOT_YET_AVAILABLE` with `UPSTREAM_INPUT_MISSING`, or with `CLOCK_UNSYNCHRONIZED` across unsynchronized clocks |
| `latency.order_to_fill` | `first_fill_at − order_submitted_at` | SECONDS · n/a | as above | 1 | as `latency.signal_to_order` |
| `benchmark.movement` | benchmark return over **exactly** the trade or period boundaries used, stating `PRICE_RETURN` or `TOTAL_RETURN` | RATIO · benchmark beginning value | same calendar and boundaries as the subject | 2 points | `PARTIAL` on a gapped benchmark |
| `coverage` | `present / requested` over the requested extent | RATIO · requested extent | request window | 0 | `NOT_YET_AVAILABLE` with `EXTENT_NOT_DETERMINABLE` when the requested extent cannot be resolved. **`UNKNOWN` is a `completeness` value and is never an availability state** |
| `freshness.source_age` | `evaluation_time − source_effective_time`, **per required input**, reported for the **oldest** required input and assessed against **that input's own** contract. §3.1 governs | SECONDS · n/a | UTC, monotonic where available | 0 | `NOT_YET_AVAILABLE` with `SOURCE_TIMESTAMP_MISSING`; `NOT_YET_AVAILABLE` with `CLOCK_UNSYNCHRONIZED` beyond tolerance — **never clamped to zero** |
| `freshness.projection_lag` | `projected_time − source_effective_time` of the newest required input the projection consumed — how far behind its sources the build is. **A separate number from source age, and never a substitute for it** | SECONDS · n/a | UTC | 0 | as `freshness.source_age` |
| `freshness.build_age` | `evaluation_time − projected_time` — how long ago this row was built. **The least interesting of the three, and the only one a rebuild resets** | SECONDS · n/a | UTC | 0 | as `freshness.source_age` |

**Cost treatment applies to every economic metric above and is stated on every value**, as one of
`GROSS`, `NET_COMMISSIONS` or `NET_ALL_COSTS` — the last meaning net of commissions, fees, borrow
and financing. **Two values with different cost treatments are never compared, summed or placed in
one series.**

**Sign convention applies to every economic metric above.** Profit is positive and loss is negative
**for both long and short**, so a profitable short is positive. **Exposure carries a magnitude and a
direction and never a profit sign**, and the two are separate fields.

#### 12.3.1 Slippage, worked through

**The unit is basis points, so the ratio is multiplied by 10,000.** A formula that divides two prices
and calls the quotient `BPS` is out by four orders of magnitude, and the error is invisible on any
single fill.

```text
slippage_bps = side_sign * (fill_price - reference_price) / reference_price * 10,000

side_sign   +1  BUY_TO_OPEN     +1  BUY_TO_COVER
            -1  SELL_TO_CLOSE   -1  SELL_TO_OPEN

positive    ADVERSE -- the fill cost more than the reference said
negative    FAVOURABLE -- the fill was better than the reference
zero        the fill matched the reference exactly
```

**Four cases, hand-calculated, and the convention is what makes them agree.**

| Side | Reference | Fill | Ratio | × 10,000 | `side_sign` | Result | Reading |
|---|---|---|---|---|---|---|---|
| buy | 100.00 | 100.10 | `+0.001` | `+10` | `+1` | **+10 bps** | paid 10 bps more — **adverse** |
| sell | 100.00 | 99.90 | `−0.001` | `−10` | `−1` | **+10 bps** | received 10 bps less — **adverse** |
| buy | 100.00 | 99.95 | `−0.0005` | `−5` | `+1` | **−5 bps** | paid less — **favourable** |
| sell | 100.00 | 100.05 | `+0.0005` | `+5` | `−1` | **−5 bps** | received more — **favourable** |

**A buy 10 bps above its reference and a sell 10 bps below it are the same cost**, and `side_sign` is
what makes both report `+10` rather than `+10` and `−10`. **Without it, an equally-weighted book of
adverse buys and adverse sells averages to zero and reports perfect execution.**

**Precision is stated, and rounding happens once.** A value carries a decimal string and its `scale`;
**the declared minimum scale is two decimal places of a basis point**, so `8.42` survives and is not
truncated to `8`. Rounding is **half-even at the declared scale, applied to the final value only** —
never to intermediate quotients, and never per fill before aggregation.

**Missing and degenerate inputs refuse rather than resolve.** A fill with no named reference price is
`NOT_YET_AVAILABLE` with `UPSTREAM_INPUT_MISSING`; **a zero reference price is `NOT_APPLICABLE` with
`DENOMINATOR_ZERO`**, never a division and never a substituted price. A reference price whose
timestamp is unusable is `NOT_YET_AVAILABLE` with `SOURCE_TIMESTAMP_MISSING`, because a reference
that cannot be placed in time is not a reference.

**Slippage measures a fill; it never restates one.** The costs-already-in-the-fill rule of §12.4
governs: an actual fill price already incorporates what was crossed, so this metric **reports** that
against a reference and is **never subtracted from the same fill's economics again**.

### 12.4 The hard cases, decided rather than left open

| | |
|---|---|
| **external cash flows** | deposits and withdrawals are `cashflow.external` and **are never profit**. Return is `return.time_weighted` by default; `return.money_weighted` exists, is labelled, and is returned only when asked for. **`return.naive` does not exist** |
| **cash-flow-adjusted drawdown** | the equity series used for drawdown is adjusted so an external flow produces **no** drawdown and **no** new peak. A withdrawal that looked like a 20% loss is the defect this removes |
| **realized versus unrealized** | separate metrics. `pnl.combined` exists, is labelled combined, and **is never presented as realized** |
| **partial fills** | economics are weighted by **filled** quantity at each stage. An entry still filling has no `risk.initial_planned` yet, and reports `NOT_YET_AVAILABLE` |
| **partial exits** | **a partial exit reduces a trade; it does not close it and does not create a second one.** Realized and unrealized both move; `risk.initial_planned` does not |
| **adds and pyramids** | each add carries its **own** `risk.initial_planned` record at its own reference price and as-of, and **the original record is retained unchanged**. The trade-level denominator is the **sum of the retained per-stage initial planned risks**, and a trade whose stages carry different `risk_policy_version` values reports its `r_multiple` with every contributing policy version displayed. **No stop movement, protection change or size change alters any retained record** |
| **a moving stop** | changes `risk.open_planned` and **never** `risk.initial_planned`, so the R denominator does not drift with a trailing stop |
| **benchmark alignment** | the benchmark is aligned to the **exact** boundaries the subject used, and states `PRICE_RETURN` or `TOTAL_RETURN`. **A price-return benchmark is never compared against a total-return portfolio** |
| **corporate-action adjustment** | adjusted prices and actual fill prices are different series, labelled as such. **An actual fill is never restated by an adjustment factor** |
| **costs already in the fill** | **an actual fill price already incorporates the spread crossed and the slippage realized.** `slippage` measures that fill against a named reference; it is **never** subtracted again from the same fill's economics, and no modelled spread or slippage estimate is applied on top of an actual fill. A **hypothetical** outcome — a counterfactual, a backtest, a shadow result — has no actual fill, so it states its modelled spread, slippage and capacity assumptions explicitly, and is **never placed in a series with realized results** |
| **MFE, MAE and capture ratio units** | `capture_ratio` requires its numerator and `mfe` in the **same unit, frequency and price basis**. A realized outcome in USD over an MFE in R is refused rather than divided |
| **latency clocks** | every latency states its clock source and accuracy. **A latency across two unsynchronized clocks is `NOT_YET_AVAILABLE` with `CLOCK_UNSYNCHRONIZED`, not a small number** |
| **undefined ratios** | a zero denominator yields `NOT_APPLICABLE` with `DENOMINATOR_ZERO` — one of the **two** routes to `NOT_APPLICABLE` in the §4.1.1 matrix, the other being `NOT_DEFINED_FOR_SUBJECT`. **Never infinity, never a sentinel, never a large number** |
| **provisional versus final attribution** | provisional is labelled, and finalization is a recorded event |
| **insufficient samples** | `INSUFFICIENT_OBSERVATIONS` rather than a computed number, against the declared minimum |
| **missing price paths** | `PARTIAL` for every path-dependent metric, and **the affected metrics are named** |
| **inapplicable versus unavailable** | `NOT_APPLICABLE` requires `NOT_DEFINED_FOR_SUBJECT` — the subject has no such property — or `DENOMINATOR_ZERO` — the arithmetic is undefined. **Everything else that is simply absent is unavailable**, with the state and the reason code the §4.1.1 matrix permits, and **`UPSTREAM_INPUT_MISSING` never reaches `NOT_APPLICABLE`** |

### 12.5 Display sufficiency is not evidence of validity

**This dictionary makes numbers displayable. It does not make a strategy valid, and it must never be
read as doing so.**

| | |
|---|---|
| **display sufficiency** | the number has a definition, a unit, a denominator, a basis, a cost treatment, a minimum-observation rule and a stated unavailable outcome. **That is what this section provides** |
| **evidence of validity** | preregistration, a named baseline, a locked out-of-sample evaluation with its exposure disclosed, tracked trials including failed and abandoned runs, multiple-testing control, stress and capacity analysis, and a human governance decision. **That is [`feedback-self-maturation-specification.md`](feedback-self-maturation-specification.md), and none of it has been run** |

**A metric that passes every rule here is still not a finding.** A Sharpe above its minimum
observation count is a computed number, not a validated edge; an expectancy over thirty trades is a
sample, not a claim. **No performance figure is invented anywhere in this document, no strategy is
described as validated, and no alpha is claimed.**

### 12.6 Definitions and authority

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
