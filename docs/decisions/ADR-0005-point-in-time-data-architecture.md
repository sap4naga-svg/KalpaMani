# ADR-0005 — Point-in-Time Data Architecture and the Anti-Lookahead Contract

- **Status:** **Proposed** — planning under review. Not accepted, not implemented.
- **Date:** 2026-08-26 (revision 4)
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
| **3** | **2026-08-26** | Review of revision 2. Three contract inconsistencies fixed: availability is now **origin-aware**, so a proprietary observation with no public release instant is usable where it legitimately can be (§1a, §2a); the `DECLARE` resolution for unknown provider timing is **withdrawn** as self-contradictory and replaced by EXCLUDE / BOUND / DOWNGRADE (§4); and the revision-view table's "default" is reworded to **normative historical view**, since the accessor has no default (§6). |
| **4** | **2026-08-26** | Review of revision 3. The **atomic-fact rule** is added (§0); a **derived-artifact model** replaces the unrepresentable "inherited" origin (§1b); a single origin-aware **`source_anchor`** replaces the public-time-only class invariants (§7); exact provider/public times are separated from **conservative upper bounds** (§4a); the manifest records **requested versus resolved profile** (§18a); and **required-input completeness** is enforced rather than merely reported (§19a). Four schemas that mixed facts are split. |

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

### 0. The atomic-fact rule

> **One fact row has exactly one `information_origin`, exactly one `temporal_fact_class`, and
> exactly one availability envelope.** A row may not combine independently changing facts
> merely because they share an event or a security identity.

The test: **if two values can change at different times, for different reasons, from different
sources, they are two facts.** They may share an identifier; they may not share an envelope.

Revision 3 broke this in four places, and the breakage was not cosmetic. A single
`earnings_event` row carried a scheduled date, a realised release, a provider consensus and a
computed surprise — four facts, three origins, two temporal classes, one set of timestamps.
Whichever timestamps that row carried, three of the four were wrong. The four schemas are split
in [conceptual-schema.md](../phase3/conceptual-schema.md) §4, §6, §9–§9a, §10–§10d, §15.

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

### 1a. Records declare an information origin, and it decides what they need

**New in revision 3.** Decision 1 as written made `public_available_time` a de facto
prerequisite everywhere. That is right for a filing and wrong for a proprietary observation —
an analyst consensus snapshot or a broker-specific borrow quote has no authoritative public
release instant, and revision 2 would have made both permanently unusable, including under
`FORWARD_SYSTEM`, the profile that describes data we demonstrably held.

Every record declares an `information_origin` from a closed vocabulary:

| Origin | The fact is | `public` | `provider` | `seen` |
|---|---|---|---|---|
| `AUTHORITATIVE_PUBLIC` | publicly released at an instant independent of any vendor | **required** | optional | required |
| `PROVIDER_DERIVED` | the provider own computed or proprietary observation | **null** | **required** | required |
| `SYSTEM_OBSERVED` | observed directly by KalpaMani, with no vendor timestamp | null | null | **required** |

**A null `public_available_time` means two opposite things**, and they are distinguished by
`availability_derivation`: `UNKNOWN` means a public time exists and we failed to establish it —
the record is unusable everywhere; `NOT_APPLICABLE` means no such time exists — the record
stays usable where its origin allows. Conflating them is what revision 2 did.

Origin is a property of the fact, not of the delivery path: a filing delivered by a vendor is
still `AUTHORITATIVE_PUBLIC`, and `PROVIDER_DERIVED` is not an escape hatch for a public fact
whose timing we could not pin down.

### 1b. Derived artifacts get their own envelope

**New in revision 4.** The three source origins cannot describe a value *we computed* — a
universe snapshot, an adjusted-bar cache, a TTM aggregate, a ratio, an earnings surprise, a
factor-ready snapshot. Revision 3 papered over this by calling `universe_membership`'s origin
"inherited", which the closed enum had no value for.

**Design chosen: a separate derived envelope**, with the discriminator in the same
`information_origin` field so there is exactly one place to look — which decision 0 requires.

```
information_origin ∈ {AUTHORITATIVE_PUBLIC, PROVIDER_DERIVED, SYSTEM_OBSERVED}
        -> SOURCE envelope    public / provider / system_first_seen
information_origin = DERIVED_ARTIFACT
        -> DERIVED envelope   lineage + artifact_first_built_time
```

A derived row carries **complete input lineage**, `artifact_first_built_time`,
`derivation_spec_version` and `artifact_content_hash`, and **none** of the three source times.

| Profile | `decision_available_time` |
|---|---|
| `PUBLIC_PIT` | `max` over inputs of `dat(input, PUBLIC_PIT)` |
| `PROVIDER_REALISTIC_PIT` | `max` over inputs of `dat(input, PROVIDER_REALISTIC_PIT)` |
| `FORWARD_SYSTEM` | `max( max over inputs of dat(input, FORWARD_SYSTEM), artifact_first_built_time )` |

Rules:

- **Eligibility is the intersection of its inputs' eligibility.** An artifact built on a
  proprietary consensus is ineligible under `PUBLIC_PIT`; no arithmetic makes an input public.
- **A derived artifact never invents public or provider availability.** It has none.
- **Rebuilding does not rewrite historical input availability.** A rebuild from the same lineage
  keeps `artifact_first_built_time`; a rebuild from different lineage is a different artifact
  with its own key and hash, superseding rather than mutating.
- **Materialised artifacts stay keyed** by profile, dataset versions and content hash (§8).

`artifact_first_built_time` enters only under `FORWARD_SYSTEM`, because that is the only profile
asking what *we* held — and we did not hold a computed value before we computed it. Under the
other two the artifact is exactly as available as its slowest input, which is the honest answer
to "when could this have been calculated?".

### 2. The governing time is computed per information-set profile, not stored

```
PUBLIC_PIT              = public_available_time                      requires public
PROVIDER_REALISTIC_PIT  = max(public, provider) over non-null times  requires provider
FORWARD_SYSTEM          = max(public, provider, seen) over non-null  requires seen
```

`decision_available_time` is **not a column**. Storing it would bake one profile into the data.

### 2a. Profile eligibility is defined per origin

| Origin | `PUBLIC_PIT` | `PROVIDER_REALISTIC_PIT` | `FORWARD_SYSTEM` |
|---|---|---|---|
| `AUTHORITATIVE_PUBLIC` | eligible | eligible | eligible |
| `PROVIDER_DERIVED` | **ineligible** | eligible | eligible |
| `SYSTEM_OBSERVED` | **ineligible** | **ineligible** | eligible |

A profile serves only facts whose originating information set it can describe. `PUBLIC_PIT`
asks what the market could have known, and a proprietary consensus was never public — so
excluding it is correct, not a limitation to apologise for. `FORWARD_SYSTEM` asks what we
held, and `system_first_seen_time` answers that for every origin; public and provider times
remain **provenance and quality inputs**, not prerequisites.

**Ineligible rows are excluded and counted**, with `ORIGIN_INELIGIBLE_ROWS_EXCLUDED` in the
manifest. A factor that quietly lost its estimate inputs is worse than one that refused.

**The ordering invariant now carries its precondition.** `PUBLIC_PIT <=
PROVIDER_REALISTIC_PIT <= FORWARD_SYSTEM` may be asserted **only for a record eligible under
the profiles being compared**. Revision 2 asserted it unconditionally, which would have raised
on correct proprietary data — a malformed comparison reported as a data defect.

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

**A backfilled record must not become historically available under `PROVIDER_REALISTIC_PIT`
merely because the public fact underneath it is old.** The age of the underlying event says
nothing about when a subscriber could have obtained the vendor row describing it. `BOUND`
(§4) enforces this by construction: it sets provider availability to the day we first saw the
row, so a backfill stays inadmissible in the past rather than relying on vigilance.

### 4. Unknown provider availability: EXCLUDE, BOUND or DOWNGRADE — never DECLARE

**Revision 2 `DECLARE` is withdrawn.** It served a row on `public_available_time` while
labelling the result `PROVIDER_REALISTIC_PIT` — exactly the profile mixing decision 3 forbids.
A rule cannot both permit and prohibit the same act, and revision 2 did.

Under `PROVIDER_REALISTIC_PIT`, a null `provider_available_time` is resolved per dataset as
exactly one of:

| Resolution | Effect | Token |
|---|---|---|
| **`EXCLUDE`** | the record does not participate | `PROVIDER_AVAILABILITY_UNKNOWN` |
| **`BOUND`** | `provider_available_upper_bound` is set from `system_first_seen_time` (`FIRST_SEEN_UPPER_BOUND`); **`provider_available_time` stays null** (see 4a) | `PROVIDER_AVAILABILITY_UNKNOWN`, `PROVIDER_TIME_BOUNDED` |
| **`DOWNGRADE`** | **the entire result** runs under `PUBLIC_PIT` | `PROFILE_DOWNGRADED_TO_PUBLIC` |

> **Never serve a row using `PUBLIC_PIT` timing while labelling the result
> `PROVIDER_REALISTIC_PIT`.**

`BOUND` is sound because we cannot have been served a row before we first saw it, so
`system_first_seen_time` is a genuine upper bound — it can only delay a record, never advance
one. It is recorded **as a bound** (§4a), leaving the exact field null so a bounded row is never
mistaken for a precisely-stamped one. It is unavailable for `SYSTEM_OBSERVED` rows, where
bounding a provider time would invent one.

### 4a. Exact times and conservative bounds are different fields

**Revision 3 wrote `system_first_seen_time` into `provider_available_time` under `BOUND`.** That
field means *the instant the provider first offered this record*; the day we first saw it is an
upper bound on that instant, not the instant. Overwriting one with the other destroys the
provenance the field exists to carry and makes a bounded row indistinguishable from a
precisely-stamped one.

**Decision.** Exact and bound are separate fields — `provider_available_time` /
`provider_available_upper_bound`, and symmetrically `public_available_time` /
`public_available_upper_bound`. A bound is never written into an exact field; an exact time is
never inferred from a bound. The governing computation reads exact first, then bound, and the
manifest records which basis was used per dataset (`provider_time_basis`, limitation token
`PROVIDER_TIME_BOUNDED`).

`BOUND` therefore claims only that the provider offered the row **no later than**
`system_first_seen_time` — true, and weaker than what revision 3 asserted. Backfilled rows
remain inadmissible before that bound, which is the property `BOUND` exists for.

The same correction applies to corrections: a correction with unknown public timing sets
`public_available_upper_bound`, **not** `public_available_time`
([contract §12.2](../phase3/pit-data-contract.md)).

### 5. Unknown public availability is not point-in-time under any profile

Excluded, or admitted only under an **explicitly documented, version-controlled conservative
lag** recorded in every result that depended on it. A lag applies to `public_available_time`
only; **it may never invent a `provider_available_time`.**

This is ADR-0004 §4a's reasoning applied to data instead of orders: an ambiguous state is
resolved conservatively and visibly, never optimistically and silently.

### 6. Revision views are explicit, and there is no implicit default

**Superseded from revision 1**, which stated two contradictory defaults — "as originally
reported" in one document and "highest admissible revision" in another.

| View | Returns | Status |
|---|---|---|
| `AS_KNOWN_AT_AS_OF` | latest revision whose `decision_available_time <= as_of` | **normative historical view** |
| `ORIGINAL_FILING_ONLY` | `revision_sequence = 0` only, if admissible | permitted, explicit |
| `LATEST_RESTATED` | newest revision, ignoring `as_of` | **forbidden in historical research** |

**"Normative" is a statement about correctness, not a code default.** Revision 2 called
`AS_KNOWN_AT_AS_OF` "the default" in this table while simultaneously requiring that
`revision_view` have no default — the structural rule was right and the word was wrong. The
caller names the view on every query, and `AS_KNOWN_AT_AS_OF` is what a historical query
should name unless it has a stated reason not to.

`AS_KNOWN_AT_AS_OF` is normative because it is what a decision-maker at that
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

**Revision 4 replaces the public-time anchor with an origin-aware one.** Anchoring every class
to `public_available_time` silently disabled all three invariants for `PROVIDER_DERIVED` and
`SYSTEM_OBSERVED` rows, where that field is legitimately null — a consensus snapshot stamped
*before* the moment it was sampled would have passed every check.

```
source_anchor(record) =
    AUTHORITATIVE_PUBLIC -> public_available_time     (else public_available_upper_bound)
    PROVIDER_DERIVED     -> provider_available_time   (else provider_available_upper_bound)
    SYSTEM_OBSERVED      -> system_first_seen_time
    DERIVED_ARTIFACT     -> computed from lineage under the requested profile (§1b)
```

| Class | Invariant | Examples |
|---|---|---|
| `RETROSPECTIVE` | `source_anchor >= observation_time` | bars, filings, realised releases |
| `ANNOUNCED_FORWARD` | `source_anchor >= announcement_time`; **no constraint between `effective_date` and availability** | scheduled earnings, announced splits, calendars, index changes |
| `SAMPLED_STATE` | `source_anchor >= sample_time` | borrow, classification, shares outstanding |

**`source_anchor` is used consistently** for these class invariants, revision ordering, latency,
backfill detection and every impossibility check. There is one anchor and every temporal rule
reads it.

Every entity declares a class; there is no default. Knowing a split is coming and applying its
adjustment are two different operations, and **only the second is look-ahead**.

Expressed as exact inequalities in
[data-quality-plan.md](../phase3/data-quality-plan.md) §4, with two corrections in revision 4:

- `system_first_seen_time < source_anchor` → **BLOCKING** (impossible; a timestamp is wrong)
- **latency is measured per origin** — `seen − public` for public facts, `seen − provider` for
  proprietary ones, and **not at all** for `SYSTEM_OBSERVED`, where there is no external
  delivery to be late
- `provider_available_time < public_available_time` **for the same public fact** is now
  **BLOCKING**, not a warning: a provider cannot have offered a public fact before it was
  public, so one of the two timestamps is wrong
- **backfill detection is origin-aware**, keyed on valid-time coverage plus the anchor rather
  than on public time alone

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

### 18a. A run records the profile it asked for and the profile it got

`DOWNGRADE` changes what a run actually computed, and revision 3 had nowhere to say so. The
manifest now carries `requested_profile`, `resolved_profile`, `profile_resolution` and
`profile_resolution_reason`.

**Artifacts, dataset keys and the `run_id` are keyed by `resolved_profile`**, and all four
fields plus the resolution-policy version enter the `run_id` hash — two runs differing only in
how a gap was resolved admit different rows and must not share an id.

**A downgraded run is never labelled `PROVIDER_REALISTIC_PIT`** anywhere. It carries
`PROFILE_DOWNGRADED_TO_PUBLIC` and reads as what it is.

### 19a. Required inputs are refused, not silently dropped

`ORIGIN_INELIGIBLE_ROWS_EXCLUDED` is evidence, not sufficiency. If origin filtering or
provider-time resolution empties a domain a factor **requires**, the honest outcome is not a
smaller factor — it is no factor.

Every query, factor and artifact declares each input **REQUIRED** or **OPTIONAL**. A required
domain emptied → **refuse** with `REQUIRED_INPUT_UNAVAILABLE`. An optional domain may be
dropped only where the definition says so, with counts recorded and the limitation token
emitted.

The worked case: a factor requiring analyst estimates under `PUBLIC_PIT`. Every estimate row is
`PROVIDER_DERIVED` and ineligible, so the domain empties entirely. **It must refuse.** Computing
it anyway publishes a different quantity under the same `factor_definition_version`, and nothing
downstream would say so.

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
historical accessor · `AS_KNOWN_AT_AS_OF` normative but never a code default · no
`latest`/`current` path in research code · `LATEST_RESTATED` unreachable from research ·
`data.pit` and `data.live` mutually exclusive by import · research modules cannot import
`execution` or `broker` · **every row carries an `information_origin` from the closed
vocabulary** · **`PROVIDER_DERIVED` rows refused under `PUBLIC_PIT` and served under the other
two** · **`SYSTEM_OBSERVED` rows served only under `FORWARD_SYSTEM`** · **`NOT_APPLICABLE` and
`UNKNOWN` never conflated** · **profile ordering asserted only where the record is eligible
under both sides** · **`BOUND` never applied to a `SYSTEM_OBSERVED` row** · **no row served
under `PROVIDER_REALISTIC_PIT` using public timing** · excluded-row counts declared · mixed
profiles refused · **one origin, one class, one envelope per row** · **derived artifacts carry
complete lineage and no source times** · **derived availability equals the lineage max, plus
first-built under `FORWARD_SYSTEM`** · **derived eligibility is the input intersection** ·
**rebuild from identical lineage does not move `artifact_first_built_time`** · **bounds never
written into exact fields** · **`resolved_profile` carried through every artifact and the
`run_id`** · **a required input domain emptied refuses the run** · backfill inadmissible under the profiles that forbid it · restatement
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
