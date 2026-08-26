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
>
> **Revision 5 (2026-08-26).** Normalization round. The two envelopes are made **mutually
> exclusive** rather than one being a superset (§2.4); **`resolved_public_time` /
> `resolved_provider_time`** are defined so an approved upper bound satisfies a profile
> requirement without being mistaken for an exact time (§5.0); the derivation ladder stops
> writing **lag-derived approximations into exact fields** (§5.1); every computation after
> resolution uses **`resolved_profile`** (§3.3, §7.1); provider-gap resolution becomes
> **per dataset** (§3.3); derived artifacts declare **output validity** instead of borrowing a
> source temporal class (§7.2); and required inputs carry an explicit **coverage contract**
> (§13.3).
>
> **Revision 4 (2026-08-26).** Review of revision 3 found that the closed source-origin
> vocabulary could not represent a **derived artifact** — a universe snapshot, an adjusted-bar
> cache, a TTM aggregate, an earnings surprise — and that several schemas packed facts of
> different origins and classes into one availability envelope. Revision 4 adds the
> **atomic-fact rule** (§1 R5), a **derived-artifact envelope** (§2.4), a single origin-aware
> **`source_anchor`** replacing the public-time-only class invariants (§7), and separates
> **exact provider time from a conservative upper bound** (§2.5).
>
> **Revision 3 (2026-08-26).** Review of revision 2 found that it effectively required a
> `public_available_time` on *every* record under *every* profile — which is wrong for
> proprietary observations such as an analyst consensus snapshot or a broker-specific borrow
> quote, where no authoritative public release instant exists. Records now declare an
> **`information_origin`**, and profile eligibility is defined per origin (§3.1). Revision 2's
> `DECLARE` resolution for unknown provider timing is **withdrawn** — it contradicted the
> no-profile-mixing rule — and replaced by EXCLUDE / BOUND / DOWNGRADE (§3.3). "Default
> revision view" is reworded to **normative historical view**, since the accessor has no
> default (§6).

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

> **R5 — the atomic-fact rule.** **One fact row has exactly one `information_origin`, exactly
> one availability envelope, and exactly one temporal declaration** — a `temporal_fact_class`
> if it is a source fact, an `output_validity` if it is a derived artifact (§7.2). A row may not
> combine independently changing facts merely because they share an event or a security
> identity.

R5 is the rule revision 3 was missing, and its absence produced concrete defects. A single
`earnings_event` row carried a scheduled date (announced weeks ahead), a realised release
(retrospective), a provider consensus (proprietary) and a computed surprise (derived) — four
facts with four different availability stories sharing one set of timestamps. Whichever
timestamp that row carried, three of the four were wrong.

The test for R5 is simple: **if two values on a row can change at different times, for
different reasons, from different sources, they are two facts.** They may share an identifier;
they may not share an envelope.

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
| `public_available_time` | The instant the fact first became **publicly obtainable from the authoritative source** — an SEC acceptance datetime, an exchange dissemination, a press release. A property of the world, not of any vendor. | yes — **and for a proprietary observation it is legitimately null** (§2.3) |
| `provider_available_time` | The instant **the selected provider first offered this record** in its feed or API. A property of the vendor. | yes |
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

### 2.3 `information_origin` — where the fact comes from

**New in revision 3.** Revision 2 treated `public_available_time` as the universal anchor.
That is right for a filing and wrong for a consensus estimate: nobody "publishes" a
proprietary consensus at an authoritative instant — the provider computes it, and the earliest
anyone outside the provider could act on it is when the provider served it.

Every record declares its origin, and the vocabulary is closed:

| `information_origin` | Meaning | `public` | `provider` | `system_first_seen` |
|---|---|---|---|---|
| **`AUTHORITATIVE_PUBLIC`** | The fact has an authoritative public release instant, independent of any vendor. A filing acceptance, an exchange dissemination, an issuer press release. | **required** | optional | required |
| **`PROVIDER_DERIVED`** | The fact **is** the provider's own computed or proprietary observation. No authoritative public release instant exists for it. | **must be null** | **required** | required |
| **`SYSTEM_OBSERVED`** | KalpaMani observed an external state directly — a poll of a live endpoint that carries no vendor timestamp. | null | null | **required** |
| **`DERIVED_ARTIFACT`** | **Not an observation at all.** A value KalpaMani computed from other rows. Carries the **derived envelope** (§2.5) instead of the three source times. | **null** | **null** | **null** |

The first three are **source origins** — a fact arrived from outside and the question is when.
The fourth is a discriminator: it says *this row does not describe an external observation, so
do not look for one*. Revision 3 had only the three, and had to fudge derived rows by declaring
their origin "inherited", which the closed enum could not express.

Two rules keep the vocabulary honest:

- **Origin is a property of the fact, not of the delivery path.** A 10-Q *delivered by a
  vendor* is still `AUTHORITATIVE_PUBLIC`, because the filing has its own public instant that
  the vendor did not create. A vendor's *standardised restatement* of that filing's numbers is
  still `AUTHORITATIVE_PUBLIC` too, anchored to the filing it came from.
- **If an authoritative public instant exists for this exact fact, the origin is
  `AUTHORITATIVE_PUBLIC` and `public_available_time` is required.** `PROVIDER_DERIVED` is not
  an escape hatch for a public fact whose timing we failed to establish — that case is
  `AUTHORITATIVE_PUBLIC` with `public_time_derivation = UNKNOWN`, and it is ineligible
  everywhere (§10 rule 6).
- **`DERIVED_ARTIFACT` is not an escape hatch either.** A row is derived only if *we* computed
  it. A value the provider computed and we merely received is `PROVIDER_DERIVED`, however
  derived it looks.

### 2.4 Choosing between the two envelopes

**Design decision, stated once.** The review offered two shapes: extend the origin enum with
different rules for derived rows, or keep three source origins and give derived rows their own
envelope. **This contract takes the second**, and puts the discriminator in the same field so
there is exactly one place to look — which is what R5 requires.

```
information_origin ∈ {AUTHORITATIVE_PUBLIC, PROVIDER_DERIVED, SYSTEM_OBSERVED}
        -> SOURCE envelope   (§2.1: public / provider / system_first_seen)

information_origin = DERIVED_ARTIFACT
        -> DERIVED envelope  (§2.5: lineage + artifact_first_built_time)
```

**The two envelopes are mutually exclusive, field by field.** Revision 4 described them as
alternatives but let the derived envelope inherit the source fields it merely "must not carry",
so a derived row still had to be validated as a malformed source row. They are now disjoint:

| | SOURCE fact | DERIVED artifact |
|---|---|---|
| `information_origin` | `AUTHORITATIVE_PUBLIC` · `PROVIDER_DERIVED` · `SYSTEM_OBSERVED` | `DERIVED_ARTIFACT` |
| `public_available_time` / `_upper_bound` | present per origin | **absent** |
| `provider_available_time` / `_upper_bound` | present per origin | **absent** |
| `system_first_seen_time` | **required** | **absent** |
| temporal declaration | exactly one `temporal_fact_class` | exactly one `output_validity` (§7.2) |
| `lineage` | absent | **required, complete** |
| `artifact_first_built_time` | absent | **required** |
| `derivation_spec_version`, `artifact_content_hash` | absent | **required** |
| `ingestion_time`, `dataset_version`, `quality_status`, `provider` | present | present |

The last row is the only overlap, and deliberately so: those are **physical row properties**
— when this row was written, which build it belongs to — not claims about when anyone could
have known anything.

A row carries one envelope or the other, never both, never neither. **A derived artifact never
invents public or provider availability** — it has none, and pretending otherwise is exactly
the conflation this contract exists to prevent.

### 2.5 The derived envelope

A `DERIVED_ARTIFACT` row carries these instead of the three source times:

| Field | Type | Meaning |
|---|---|---|
| `lineage` | list | **Complete** input lineage: for each input, its entity, `dataset_version`, and the row selector or upstream `artifact_id` that identifies exactly what was consumed. Not a summary — the set a rebuild would read. |
| `artifact_first_built_time` | instant | When this artifact was **first** built. Not the latest build. |
| `derivation_spec_version` | string | The version of the computation that produced it. |
| `artifact_content_hash` | string | SHA-256 of the produced value or series. |

**Availability is computed from lineage, never stored:**

```
PUBLIC_PIT             dat = max over inputs of dat(input, PUBLIC_PIT)
PROVIDER_REALISTIC_PIT dat = max over inputs of dat(input, PROVIDER_REALISTIC_PIT)
FORWARD_SYSTEM         dat = max( max over inputs of dat(input, FORWARD_SYSTEM),
                                  artifact_first_built_time )
```

**Eligibility is the intersection of its inputs' eligibility.** An artifact computed from a
`PROVIDER_DERIVED` consensus is ineligible under `PUBLIC_PIT`, because one of its inputs is —
and no amount of arithmetic makes a proprietary input public.

`artifact_first_built_time` enters only under `FORWARD_SYSTEM`, and only there, because it is
the one profile that asks what *we* held: we did not hold a computed value before we computed
it. Under the other two profiles the artifact is exactly as available as its slowest input,
which is the honest answer to "when could this have been calculated?".

**Rebuilding does not rewrite history.** A rebuild from the *same* lineage keeps
`artifact_first_built_time` — recomputing a value we already had does not move when we had it.
A rebuild from *different* lineage is a different artifact with its own key, its own hash and
its own first-built time; it supersedes rather than mutates (§8, and `dataset_version`
supersession).

### 2.6 Exact times and conservative upper bounds are different fields

**Revision 3 wrote `system_first_seen_time` into `provider_available_time` under `BOUND`.**
That field is defined as *the instant the provider first offered this record*, and the day we
first saw it is not that instant — it is an upper bound on it. Overwriting one with the other
destroys the provenance the field exists to carry, and makes a bounded row indistinguishable
from a precisely-stamped one.

Exact and bound are therefore **separate fields**, and both may be present:

| Field | Meaning |
|---|---|
| `provider_available_time` | **Exact.** The provider said so, or a dated file drop established it. Null when unknown — and it stays null. |
| `provider_available_upper_bound` | **Conservative.** A time the provider certainly offered the record *by*. Derived, and its derivation is named. |
| `public_available_time` | **Exact**, per §5.1 rules 1–4. |
| `public_available_upper_bound` | **Conservative.** Used for corrections and other records whose public timing is unknown but bounded — see §12.2. |

Rules:

- **A bound is never written into an exact field**, and an exact field is never inferred from a
  bound.
- **Where both are present, `exact_time <= upper_bound`.** A violation is **BLOCKING**: a bound
  that precedes the exact time it bounds is not a bound.
- **Approximations live in bound fields, always** (§5.1). A date-plus-lag or session-plus-lag
  value is an approximation, and revision 4 wrote both into `public_available_time` while
  calling that field exact.
- The governing computation reads **exact first, then bound**; which one was used is recorded
  per dataset in the manifest.
- **`BOUND` never claims the provider published at `system_first_seen_time`.** It claims only
  that the provider offered the row no later than then — which is true, and weaker.
- A backfilled row bounded this way stays **inadmissible before its upper bound**, which is the
  property `BOUND` exists for.

---

## 3. Information-set profiles

A profile answers one question: **whose information set are we simulating?**

| Profile | Simulates | `decision_available_time` = |
|---|---|---|
| **`PUBLIC_PIT`** | What the market could have known. | `resolved_public_time` |
| **`PROVIDER_REALISTIC_PIT`** | What a subscriber to our chosen provider could have known. | `max(resolved_public_time, resolved_provider_time)` over the values that are **present** |
| **`FORWARD_SYSTEM`** | What KalpaMani actually held. | `max(resolved_public_time, resolved_provider_time, system_first_seen_time)` over the values that are **present** |

All three read the §5.0 resolved helpers, so **an approved upper bound satisfies a requirement
exactly as an exact time does** — while remaining visibly a bound in the fields, the quality
checks and the manifest. Revision 4's table said an exact time was mandatory, which would have
made `BOUND` useless the moment it was needed.

**What each profile requires, per origin:**

| Origin | `PUBLIC_PIT` | `PROVIDER_REALISTIC_PIT` | `FORWARD_SYSTEM` |
|---|---|---|---|
| `AUTHORITATIVE_PUBLIC` | `resolved_public_time` | `resolved_public_time` **and** `resolved_provider_time` | `system_first_seen_time` |
| `PROVIDER_DERIVED` | — ineligible | `resolved_provider_time` | `system_first_seen_time` |
| `SYSTEM_OBSERVED` | — ineligible | — ineligible | `system_first_seen_time` |
| `DERIVED_ARTIFACT` | inputs eligible | inputs eligible | always (§2.5) |

The `AUTHORITATIVE_PUBLIC` row under `PROVIDER_REALISTIC_PIT` is stricter than revision 4,
deliberately: simulating a subscriber means knowing when the **subscriber** got the row, so a
public fact with no provider timing at all is not provider-realistic — it is public-PIT wearing
the wrong label, which is precisely the withdrawn `DECLARE` behaviour. It is resolved by §3.3,
not waived.

A record missing a time its profile requires is **ineligible** under that profile — never
admitted with a substitute.

### 3.1 Profile eligibility by information origin

**This is the revision-3 correction.** Revision 2 made `public_available_time` a de facto
prerequisite everywhere, which would have made an analyst consensus snapshot or a broker
borrow quote permanently unusable — including under `FORWARD_SYSTEM`, the profile that
describes data we demonstrably held.

| `information_origin` | `PUBLIC_PIT` | `PROVIDER_REALISTIC_PIT` | `FORWARD_SYSTEM` |
|---|---|---|---|
| **`AUTHORITATIVE_PUBLIC`** | **eligible** — governed by `resolved_public_time` | **eligible** — governed by `max(resolved_public_time, resolved_provider_time)` | **eligible** — governed by `max(resolved_public_time, resolved_provider_time, seen)` |
| **`PROVIDER_DERIVED`** | **INELIGIBLE** — there is no public instant to simulate | **eligible** — governed by `resolved_provider_time` | **eligible** — governed by `max(resolved_provider_time, seen)` |
| **`SYSTEM_OBSERVED`** | **INELIGIBLE** | **INELIGIBLE** — no provider instant exists | **eligible** — governed by `seen` |
| **`DERIVED_ARTIFACT`** | eligible **iff every input is** | eligible **iff every input is** | **always eligible**, governed by `max(inputs, artifact_first_built_time)` |

Read down the columns and the rule is simple: **a profile can only serve a fact whose
originating information set it can actually describe.**

- `PUBLIC_PIT` asks *"what could the market have known?"*. A proprietary consensus was never
  public, so the question has no answer for it. Excluding it is correct, not a limitation to
  declare.
- `PROVIDER_REALISTIC_PIT` asks *"what could a subscriber have known?"*. For a proprietary
  fact that is exactly `provider_available_time`, and **no public time is required**. Where a
  public time also exists and applies to the same fact, the **later** of the two governs, per
  §12.5.
- `FORWARD_SYSTEM` asks *"what did we hold?"*. `system_first_seen_time` answers it for every
  origin. Public and provider times remain **provenance and quality inputs** — they still
  police the contradiction checks in §3.4 — but they are **not prerequisites** for a fact
  KalpaMani actually observed.

**Ineligibility is recorded, not silent.** A query whose datasets contain rows ineligible
under the requested profile reports the excluded row counts by dataset and origin, and the
manifest carries `ORIGIN_INELIGIBLE_ROWS_EXCLUDED`. A factor that quietly lost its estimate
inputs is worse than one that refused to compute.

### 3.2 Worked examples

**A — SEC filing. `AUTHORITATIVE_PUBLIC`; all three times applicable.**

```
public    2025-02-14T21:31:07Z   8-K acceptance datetime
provider  2025-02-15T04:00:00Z   vendor file drop the following morning
seen      2026-03-02T02:14:00Z   we backfilled this in March 2026

PUBLIC_PIT              -> 2025-02-14T21:31:07Z   eligible
PROVIDER_REALISTIC_PIT  -> 2025-02-15T04:00:00Z   eligible
FORWARD_SYSTEM          -> 2026-03-02T02:14:00Z   eligible
```

All three profiles answer, and the ordering invariant holds because the record is eligible
under all three.

**B — proprietary analyst consensus snapshot. `PROVIDER_DERIVED`; no public instant exists.**

```
public    NULL                   nobody published this consensus
provider  2025-02-13T23:00:00Z   the provider's end-of-day snapshot
seen      2026-03-02T02:14:00Z

PUBLIC_PIT              -> INELIGIBLE   the question has no answer for this fact
PROVIDER_REALISTIC_PIT  -> 2025-02-13T23:00:00Z   eligible
FORWARD_SYSTEM          -> 2026-03-02T02:14:00Z   eligible
```

Under revision 2 this row was effectively unusable. It is now usable in the two profiles that
can describe it, and honestly absent from the one that cannot.

**C — IBKR borrow snapshot. `PROVIDER_DERIVED`; broker-specific, no public instant.**

```
public    NULL                   IBKR's book is not a public dissemination
provider  2025-02-13T12:30:00Z   stamped by the source, once qualified
seen      2025-02-13T12:31:44Z   our poll

PUBLIC_PIT              -> INELIGIBLE
PROVIDER_REALISTIC_PIT  -> 2025-02-13T12:30:00Z   eligible
FORWARD_SYSTEM          -> 2025-02-13T12:31:44Z   eligible
```

If the source carries **no** timestamp of its own and we merely polled it, the origin is
`SYSTEM_OBSERVED` instead, and only `FORWARD_SYSTEM` is eligible. Which of the two applies to
IBKR is part of the Phase-3C qualification checklist
([implementation-plan.md](implementation-plan.md) §4.1), not an assumption.

### 3.3 Unknown provider availability — EXCLUDE, BOUND or DOWNGRADE

**Revision 2's `DECLARE` resolution is withdrawn.** It served a row using
`public_available_time` while labelling the result `PROVIDER_REALISTIC_PIT`, which is exactly
the profile mixing §3.4 forbids. A rule cannot both permit and prohibit the same act.

`resolved_provider_time` will often be null, because most vendors do not say when a row entered
their feed. Under `PROVIDER_REALISTIC_PIT` that is resolved in exactly one of three ways:

| Resolution | Scope | Effect | Limitation token |
|---|---|---|---|
| **`EXCLUDE`** | **per dataset** | The dataset's unresolvable records do not participate. | `PROVIDER_AVAILABILITY_UNKNOWN` |
| **`BOUND`** | **per dataset** | `provider_available_upper_bound` is set from `system_first_seen_time` with `provider_bound_derivation = FIRST_SEEN_UPPER_BOUND`. **`provider_available_time` stays null** (§2.6). The row participates at the bounded time. | `PROVIDER_AVAILABILITY_UNKNOWN`, `PROVIDER_TIME_BOUNDED` |
| **`DOWNGRADE`** | **global** | **The entire run** executes under `PUBLIC_PIT`. Not the dataset — the run. | `PROFILE_DOWNGRADED_TO_PUBLIC` |

#### Scope matters, and revision 4 flattened it

A run legitimately uses **different policies for different datasets** — `BOUND` for a
fundamentals feed whose `lastupdated` means *last changed*, `EXCLUDE` for a feed with no usable
timing at all. Revision 4 recorded one scalar `profile_resolution` for the whole run, so those
two runs were indistinguishable in the manifest and collided in `run_id`.

**`EXCLUDE` and `BOUND` are per-dataset policies. `DOWNGRADE` is global and changes
`resolved_profile`.** The manifest carries a canonical, dataset-ordered map of the per-dataset
policies with exact/bounded/excluded row counts and a reason
([reproducibility-and-provenance.md](reproducibility-and-provenance.md) §2), and **that whole
map plus `resolution_policy_version` enters the `run_id`**. Two runs that resolved the same
query differently admit different rows and must not share an identity.

> **Never serve a row using `PUBLIC_PIT` timing while labelling the result
> `PROVIDER_REALISTIC_PIT`.** That is the rule revision 2 broke.

`BOUND` is the useful middle option and it is genuinely conservative: we cannot have been
served a row before we first saw it, so `system_first_seen_time` is a sound upper bound on
provider availability. It can only ever *delay* a record, never advance it — and per §2.6 it
is recorded as a **bound**, leaving `provider_available_time` null so that a bounded row is
never mistaken for a precisely-stamped one.

`DOWNGRADE` is honest in a different way — it relabels the whole result rather than pretending
a mixed run is a provider-realistic one. **A downgraded run is labelled `PUBLIC_PIT` end to
end**, in the manifest and in the `run_id` (§13.2).

`BOUND` is unavailable for a `SYSTEM_OBSERVED` record for the obvious reason: there is no
provider, so bounding a provider time would invent one.

### 3.4 Backfill semantics, per profile

A vendor supplies, today, records describing events from 2015.

| Profile | Admissible in a 2015 query? |
|---|---|
| `PUBLIC_PIT` | **Yes** — *if and only if* the origin is `AUTHORITATIVE_PUBLIC` and public timing is proven (§5.1 rule 1 or 2). Otherwise no. |
| `PROVIDER_REALISTIC_PIT` | **No.** A backfill may not become available before the provider supplied it. If `provider_available_time` is today, the record is inadmissible in 2015. If it is unknown, §3.3 applies — and note that **`BOUND` sets it to today**, so a backfilled row stays inadmissible. |
| `FORWARD_SYSTEM` | **No.** A backfill may never precede `system_first_seen_time`. |

> **A backfilled record must not become historically available under
> `PROVIDER_REALISTIC_PIT` merely because the public fact underneath it is old.** The age of
> the underlying event says nothing about when a subscriber could have obtained the vendor's
> row describing it. `BOUND` is designed so that this holds by construction rather than by
> vigilance.

**Mixing is forbidden.** A run that admits rows under one profile's reasoning while labelling
itself another is refused at manifest emission, not annotated.

### 3.5 What each profile is for

| Profile | Legitimate use | Never valid for |
|---|---|---|
| `PUBLIC_PIT` | Exploratory factor research; academic-style questions about whether an effect exists in the market at all. | Any claim about what *this system* could have captured. Any factor built on proprietary observations, which are ineligible. |
| `PROVIDER_REALISTIC_PIT` | Backtests intended to inform capital deployment, where the provider is the one we would actually run on. | Any claim about latency or operational reality we have not measured. |
| `FORWARD_SYSTEM` | **Mandatory** for any forward, paper or micro-live validation claim. The only profile whose inputs we actually observed. | Long histories, since it cannot reach back before we existed. |

**Which profile governs production research is a decision gate, not settled here**
(ADR-0005, gate G2). The proposal is `PROVIDER_REALISTIC_PIT` for anything that informs
capital, `PUBLIC_PIT` permitted for exploration with its exclusions declared, `FORWARD_SYSTEM`
required for forward validation. That proposal awaits the provider decision, because
`provider_available_time` is only obtainable for a provider we have chosen.

### 3.6 The ordering invariant, and its precondition

For a record eligible under all three profiles:

```
PUBLIC_PIT  <=  PROVIDER_REALISTIC_PIT  <=  FORWARD_SYSTEM
```

so a result under a more conservative profile can never see more than one under a less
conservative profile.

**The precondition is not decoration.** The ordering may be asserted **only across profiles
under which the record is eligible** (§3.1). Comparing a `PROVIDER_DERIVED` record's
`PROVIDER_REALISTIC_PIT` time against a `PUBLIC_PIT` time it does not have is not a violated
invariant — it is a malformed comparison, and revision 2's unconditional assertion would have
raised on correct data.

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

### 5.0 Resolved times — one exact-or-approved-bound helper per axis

Two derived helpers, computed and **never stored as source facts**:

```
resolved_public_time(r)   = public_available_time
                            else public_available_upper_bound, if its
                                 public_bound_derivation is APPROVED for r's dataset
                            else NULL

resolved_provider_time(r) = provider_available_time
                            else provider_available_upper_bound, if its
                                 provider_bound_derivation is APPROVED for r's dataset
                            else NULL
```

**"Approved" is doing real work.** A bound satisfies a profile requirement only when its
derivation appears in the dataset's configured approved list. That stops an arbitrary
approximation from silently qualifying a record, and it keeps the choice a governed one rather
than a property of whichever ingestion path ran.

These helpers are used **consistently** in profile computation, profile eligibility,
`source_anchor` (§7.1), `as_of` filtering, backfill handling, every quality check, and the
manifest. Exact-versus-bound provenance survives all of it: the helper returns a *value*, and
the fields it came from stay exactly where they were.

### 5.1 Public timing — exact fields and bound fields

Revision 4 called `public_available_time` exact and then wrote date-plus-lag and
session-plus-lag values into it. Approximations now go where approximations belong.

**Exact — writes `public_available_time`:**

| # | Situation | `public_time_derivation` |
|---|---|---|
| 1 | Authoritative machine timestamp exists (e.g. a filing acceptance datetime) | `AUTHORITATIVE_TIMESTAMP` |
| 2 | The source supplies a publication timestamp **with** an unambiguous timezone | `VENDOR_TZ_TIMESTAMP` |

**Bound — writes `public_available_upper_bound`, leaving the exact field null:**

| # | Situation | `public_bound_derivation` |
|---|---|---|
| 3 | Publication **date** only | `DATE_PLUS_LAG` (§9) |
| 4 | Tied to a session (e.g. a daily bar) | `SESSION_CLOSE_PLUS_LAG` (§9) |
| 5 | A correction whose public timing is unknown but which we demonstrably held | `FIRST_SEEN_UPPER_BOUND` (§12.2) |

**Neither:**

| # | Situation | Effect |
|---|---|---|
| 6 | None of the above, **and the origin is `AUTHORITATIVE_PUBLIC`** | both null, `public_time_derivation = UNKNOWN`. **Not point-in-time under any profile** |
| 7 | The origin is `PROVIDER_DERIVED` or `SYSTEM_OBSERVED` | both null, `public_time_derivation = NOT_APPLICABLE`. Eligible exactly where §3.1 allows |

**Rules 6 and 7 look alike and are opposites**, which is why they are separate rows. Both
produce a null. In rule 6 the null means *we failed to establish a time that exists*, and the
record is unusable everywhere. In rule 7 it means *no such time exists to establish*, and the
record is perfectly usable under `PROVIDER_REALISTIC_PIT` and `FORWARD_SYSTEM`.

Rule 6 is the one that matters for public facts. "The vendor gave us history, so it must be
historical" is the reasoning that produces look-ahead, and it is the same shape of reasoning
[BLUEPRINT_ERRATA](../architecture/BLUEPRINT_ERRATA.md) E-001 already caught once in a
different domain: an assumption about an external system that nobody had tested.

### 5.2 `provider_available_time`

**Exact — writes `provider_available_time`:**

| # | Situation | `provider_time_derivation` |
|---|---|---|
| 1 | The provider stamps rows with a feed-publication or `lastupdated` time whose semantics are **documented and verified** | `VENDOR_STAMPED` |
| 2 | The provider publishes dated file drops and we ingest from the drop | `FILE_DROP` |

**Bound — writes `provider_available_upper_bound`, leaving the exact field null:**

| # | Situation | `provider_bound_derivation` |
|---|---|---|
| 3 | We have observed the record continuously since a known ingestion | `FIRST_SEEN_UPPER_BOUND` — the `BOUND` resolution of §3.3 |
| 4 | The provider publishes a delivery window rather than an instant | `DELIVERY_WINDOW` |

**Neither:**

| # | Situation | Effect |
|---|---|---|
| 5 | Origin is `PROVIDER_DERIVED` or `AUTHORITATIVE_PUBLIC`, and nothing above applies | both null, `provider_time_derivation = UNKNOWN` → §3.3 |
| 6 | Origin is `SYSTEM_OBSERVED` | both null, `provider_time_derivation = NOT_APPLICABLE` |

Rule 1 carries a trap worth naming: a vendor `lastupdated` column usually means "when this
row last changed", not "when this row first appeared". The two coincide only for rows that
never changed. **Verifying which one a vendor means is a Phase-3A provider test**, not an
assumption ([implementation-plan.md](implementation-plan.md) §2, test P1).

**A `SYSTEM_OBSERVED` record has no `provider_available_time` and none may be invented for
it** — including by `BOUND`, which bounds a provider time that exists but is unstated, not one
that does not exist at all.

### 5.3 `system_first_seen_time`

The `ingestion_time` of the earliest `ingestion_run` that delivered this logical record. Never
derived, never estimated, and never later than the row's own `ingestion_time`.

---

## 6. Revision views

The first draft said both "research defaults to as-originally-reported" and "the highest
`revision_sequence` admissible at `as_of`". Those are different rules and the draft applied
each in a different document. Corrected here.

**They are different questions**, and the fix is to stop having *any* implicit answer:

| View | Returns | Status |
|---|---|---|
| **`AS_KNOWN_AT_AS_OF`** | The **latest** revision whose `decision_available_time <= as_of`. If a restatement had already been published by `as_of`, it is returned; otherwise the original is. | **normative historical view** |
| **`ORIGINAL_FILING_ONLY`** | `revision_sequence = 0` only, and only if admissible at `as_of`. Later restatements are invisible whatever the cutoff. | permitted, explicit |
| **`LATEST_RESTATED`** | The newest revision, **ignoring `as_of` entirely**. | **forbidden in historical research** |

> **"Normative historical view" is a statement about correctness, not a code default.**
> `AS_KNOWN_AT_AS_OF` is what a historical query *should* ask for unless it has a stated reason
> not to — and the caller still has to say so, every time (§6.2). Revision 2 called it "the
> default" in this table while §6.2 forbade defaults; the rule was right and the word was
> wrong.

`AS_KNOWN_AT_AS_OF` is normative because it is what a decision-maker at that moment would
actually have had in front of them — including any restatement already published. It is *not*
the same as "as originally reported", and revision 1 conflated them.

`ORIGINAL_FILING_ONLY` is the right choice for questions specifically about first-reported
figures — a surprise measured against what was first announced, for instance. It is a
deliberate research choice, and it is no harder to ask for than the normative one.

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

### 7.1 `source_anchor` — one origin-aware availability anchor

**Revision 3 anchored every class to `public_available_time`.** That silently disabled all
three invariants for `PROVIDER_DERIVED` and `SYSTEM_OBSERVED` rows, where the public time is
legitimately null — a consensus snapshot stamped *before* the moment it was sampled would have
passed every check. The anchor is now origin-aware:

```
source_anchor(record) =
    AUTHORITATIVE_PUBLIC -> resolved_public_time(record)     (§5.0)
    PROVIDER_DERIVED     -> resolved_provider_time(record)   (§5.0)
    SYSTEM_OBSERVED      -> system_first_seen_time
    DERIVED_ARTIFACT     -> computed from lineage under the RESOLVED profile (§2.5)
```

**`resolved_profile`, never `requested_profile`** (§3.3). A `DOWNGRADE` changes the whole run
*before* any filtering, anchoring or artifact construction happens; `requested_profile` survives
only as audit evidence of what was asked for.

`source_anchor` is used **consistently** for the class invariants below, revision ordering,
latency, backfill detection and every impossibility check. There is one anchor, and every
temporal rule reads it.

Every entity declares a `temporal_fact_class`:

| Class | Meaning | Timing invariant | Examples |
|---|---|---|---|
| **`RETROSPECTIVE`** | The fact is observed at or after it occurs. | `observation_time <= source_anchor` | price bars, executed trades, reported financials, an actual earnings release |
| **`ANNOUNCED_FORWARD`** | The fact is announced before it takes effect. **`effective_date` may legitimately be far later than availability.** | `announcement_time <= source_anchor`; **no constraint between `effective_date` and availability** | scheduled earnings dates, announced splits and dividends before ex-date, announced index or classification changes, future exchange sessions and holidays |
| **`SAMPLED_STATE`** | A state holding over an interval, observed by sampling. | `sample_time <= source_anchor` | borrow availability and fee, classification membership, shares outstanding |

### 7.2 Derived artifacts declare output validity, not a source class

A derived artifact was not observed, so it has no observation, announcement or sample instant
to anchor a source class against. Revision 4 let derived entities carry a `temporal_fact_class`
anyway, which meant declaring a class whose required anchor the row did not have.

**Derived artifacts declare `output_validity` instead:**

| `output_validity` | Required field(s) | Used by |
|---|---|---|
| `SESSION_SCOPED` | `effective_session` | `universe_membership` |
| `INTERVAL` | `valid_time_start`, `valid_time_end` | `adjusted_bar_artifact`, rolling and windowed factors |
| `PERIOD_END` | `period_end` | `fundamental_derived_fact` |
| `EVENT_REFERENCED` | `observation_reference` (the source row the output describes) | `earnings_surprise_artifact` |

**Availability is governed exclusively by lineage plus `artifact_first_built_time` under
`FORWARD_SYSTEM`** (§2.5). `output_validity` describes *what period the output is about*; it
never participates in an availability computation. Keeping the two apart is the whole reason
the derived envelope exists.

The class invariants in the table above therefore apply to **source facts only**. There is no
"derived `RETROSPECTIVE`".

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
> | `resolved_profile` |
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

**Every lag writes an upper-bound field, never an exact one** (§5.1), and **which bound it
writes depends on the row's origin.** A lag on an `AUTHORITATIVE_PUBLIC` row bounds public
timing; a lag on a `PROVIDER_DERIVED` row bounds provider timing. Revision 4 had one table and
applied it to public time regardless of origin, which put a lag on rows that have no public
time at all.

**Public bounds — `AUTHORITATIVE_PUBLIC` rows only:**

| Domain | Bound when exact public timing is unknown | Rationale |
|---|---|---|
| daily OHLCV, **officially disseminated** | session close + 30 min | consolidated tape settles after the close |
| corporate actions | announcement date + 1 session | announcement *time* rarely published |
| fundamentals from filings | **none needed** — acceptance datetime is exact | machine-generated |
| fundamentals with no filing link | filing date + 1 session | vendor processing lag unknown |
| earnings release, no verified time | **next session open** after the reported date | refuses to assume before-market |
| classification **observed in a filing** | filing acceptance | exact; no bound needed |

**Provider bounds — `PROVIDER_DERIVED` rows only:**

| Domain | Bound when exact provider timing is unknown |
|---|---|
| analyst estimate snapshots | snapshot date + 1 session — consensus files are end-of-day products |
| daily OHLCV, **provider-aggregated** | provider's stated publication time, else `FIRST_SEEN_UPPER_BOUND` |
| provider classification snapshots | snapshot date + 1 session |
| vendor-estimated earnings dates | file drop, else `FIRST_SEEN_UPPER_BOUND` |
| borrow availability / fee | **no bound is acceptable** — see below |

**Analyst estimates moved out of the public table**, where revision 4 had them. They are
`PROVIDER_DERIVED`: they have no public time to bound, and a lag written against one would have
been a lag on a null.

**OHLCV and classification appear in both tables**, conditional on the row's actual origin —
`bar_construction` for bars, `classification_fact_kind` for classification. Which applies is
established by provider qualification, not assumed.

**Borrow is deliberately absent a lag.** There is no conservative lag that turns *current*
borrow data into *historical* borrow data; the value simply did not exist for that date. A lag
can correct a timing error; it cannot manufacture a missing observation. That is why borrow is
a Phase 3C qualification gate and not a lag-policy row.

**No lag ever writes an exact field.** `public_available_time` and `provider_available_time`
are written only by §5.1 and §5.2 exact rules. A lag produces a bound, the bound is named by its
derivation, and `PUBLIC_TIME_BOUNDED` or `PROVIDER_TIME_BOUNDED` appears in the manifest with
exact-versus-bound row counts per dataset.

`BOUND` (§3.3) is **not** a lag: it derives an upper bound from a time we actually observed,
rather than assuming a delay. Both produce bounds; only one of them is a guess.

---

## 10. Fail-closed rules

Consistent with ADR-0004 §5 — *"It never assumes 'no record' means 'nothing happened'"*.

These are errors, not warnings, and abort the query rather than returning a degraded result:

1. `as_of_time` absent from a historical query.
2. `requested_profile` absent from a historical query, or `resolved_profile` unset after
   resolution.
3. `revision_view` absent from a query over revisable facts.
4. `revision_view = LATEST_RESTATED` reached from research or backtest code.
5. `as_of_time` later than the dataset build time.
6. A record with `public_time_derivation = UNKNOWN` participating in a point-in-time query.
   (`NOT_APPLICABLE` is **not** `UNKNOWN` — see §5.1 rules 6 and 7.)
7. A requested `as_of` earlier than the dataset declared coverage start.
8. Any `BLOCKING` data-quality issue open against a dataset the query touches.
9. A universe query for a date with no `universe_membership` snapshot.
10. Records resolved under **more than one profile** within a single result.
11. A record **served under a profile it is ineligible for** by origin (§3.1) — for example a
    `PROVIDER_DERIVED` row appearing in a `PUBLIC_PIT` result.
12. `PROVIDER_REALISTIC_PIT` requested where `provider_available_time` is null and the dataset
    resolution is not one of `EXCLUDE`, `BOUND`, `DOWNGRADE`.
13. A record served under `PROVIDER_REALISTIC_PIT` whose governing time was taken from
    `public_available_time` — the withdrawn `DECLARE` behaviour (§3.3).
14. A record missing the time its profile **requires**: no `public` under `PUBLIC_PIT`, no
    `provider` under `PROVIDER_REALISTIC_PIT`, no `system_first_seen` under `FORWARD_SYSTEM`.
15. An `information_origin` absent, or outside the closed vocabulary of §2.3.
16. `PROVIDER_DERIVED` with a non-null `public_available_time`, or `SYSTEM_OBSERVED` with a
    non-null `public` or `provider` time — the origin and the times disagree about what the
    record is.
17. A **required** input domain removed by origin filtering or provider-time resolution
    (§13.3) — refused as `REQUIRED_INPUT_UNAVAILABLE`, never silently recomputed without it.
18. A `DERIVED_ARTIFACT` row with incomplete `lineage`, or carrying any of
    `public_available_time`, `provider_available_time`, `system_first_seen_time`.
19. A `DERIVED_ARTIFACT` served under a profile **any** of its inputs is ineligible for.
20. A conservative bound written into an exact field, or an exact time inferred from a bound
    (§2.6).
21. A run whose `resolved_profile` differs from `requested_profile` while any artifact,
    dataset key or `run_id` still names the requested one (§13.2).
22. A schema version unrecognised by the reading code.
23. A checksum mismatch between a curated table and the artifacts it declares.
24. An adjusted-cache artifact that does not reproduce from its key.

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
A new revision row. The original is never overwritten.

A correction carrying no availability timestamp of its own does **not** get
`system_first_seen_time` written into `public_available_time` — revision 3 said it did, and
that is the same exact/bound conflation §2.6 corrects. Instead
`public_available_upper_bound` is set from `system_first_seen_time` with
`public_bound_derivation = FIRST_SEEN_UPPER_BOUND`, and `public_available_time` stays null.

The record is then admissible from its bound onward, which is conservative and honest: we
know the correction was public *by* the time we held it, and we do not claim to know when it
actually became public.

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
`information_set_profile` — the profile it is **requesting**, which resolution may downgrade
(§13.2). Accessors over revisable facts additionally take `revision_view`.
No defaults. No `latest` convenience. No overload without them.

```python
get_security_universe(as_of, profile)                          -> UniverseSnapshot
get_price_history(security_id, start, end,
                  adjustment_mode, as_of, profile)             -> BarSeries
get_fundamental_snapshot(security_id, period,
                         as_of, profile, revision_view)        -> FundamentalFact
get_fundamental_derived(security_id, period, metric,
                        as_of, profile, revision_view)         -> DerivedFact
get_estimate_snapshot(security_id, estimate_period,
                      as_of, profile, revision_view)           -> EstimateSnapshot
get_revision_history(security_id, start, end, as_of, profile)  -> RevisionSeries
get_earnings_schedule(security_id, period, as_of, profile)     -> EarningsSchedule
get_earnings_release(security_id, event_id, as_of, profile)   -> EarningsRelease
get_earnings_consensus(security_id, event_id, as_of, profile) -> ConsensusSnapshot
get_earnings_surprise(security_id, event_id, as_of, profile)  -> SurpriseArtifact
get_guidance_events(security_id, start, end, as_of, profile)  -> GuidanceSeries
get_borrow_snapshot(security_id, as_of, profile)               -> BorrowSnapshot
get_classification(security_id, as_of, profile)                -> Classification
```

Enforced structurally, by test, in the manner ADR-0004 §10 already uses for the execution
boundary — *"Enforced by test, not convention"*:

- **`as_of`, `profile` and `revision_view` are required and have no defaults.** A static test
  asserts no accessor declares any of them with a default value. `AS_KNOWN_AT_AS_OF` being the
  **normative** historical view (§6) does not make it a code default — the caller names it.
- **Ineligible rows are excluded and counted, never substituted.** A result whose datasets
  contain rows ineligible under the requested profile (§3.1) reports the excluded counts by
  dataset and origin, and the manifest carries `ORIGIN_INELIGIBLE_ROWS_EXCLUDED`.
- **No `latest` path exists in research code.** A static scan forbids the identifiers
  `latest`, `current`, `most_recent` and `today` in research and backtest packages, and
  forbids `LATEST_RESTATED` there entirely.
- **`adjustment_mode` is required and explicit** (§8).
- **Results carry their provenance** — `dataset_version`, `as_of`, `requested_profile`,
  `resolved_profile`, `revision_view` and every lag applied. A result that cannot say where it
  came from is not a result.
- **One accessor per fact, not per event.** The five earnings accessors above replace revision
  3's single `get_earnings_event`, because a scheduled date, a release, a consensus and a
  surprise have four different availability stories and three different origins. Returning them
  together would have forced one envelope onto four facts — the atomic-fact rule (§1 R5) in its
  original violated form.

### 13.1 Live versus historical

```
kalpamani.data.pit     historical, as_of + profile mandatory   research and backtest
kalpamani.data.live    current, as_of forbidden                live scanning only
```

Two packages, not one package with a flag. A flag is a thing that can be set wrongly; a
missing import is a thing that fails in CI. Research code importing `data.live` is a
static-test failure, the same shape as ADR-0004 §10's rule that strategy modules cannot import
execution.

### 13.2 Requested versus resolved profile

A run names the profile it **asked for** and the profile it **got**. When `DOWNGRADE` fires,
those differ, and every downstream artefact follows the **resolved** one:

| Field | Meaning |
|---|---|
| `requested_profile` | what the caller asked for |
| `resolved_profile` | what the run actually executed under |
| `profile_resolution` | `NONE` · `EXCLUDE` · `BOUND` · `DOWNGRADE` |
| `profile_resolution_reason` | why, naming the datasets that forced it |

Rules:

- **Dataset artifacts and the `run_id` are keyed by `resolved_profile`.** A downgraded run
  produces `PUBLIC_PIT` artifacts, because that is what it computed.
- **All four fields enter the `run_id` derivation** — requested, resolved, resolution and the
  resolution policy version. Two runs that differ only in how a gap was resolved are different
  runs and must not collide.
- **A downgraded run is never labelled `PROVIDER_REALISTIC_PIT`** anywhere: not in the
  manifest, not on an artifact, not in a report. It carries
  `PROFILE_DOWNGRADED_TO_PUBLIC` and reads as what it is.

Recording only the requested profile would make a downgrade invisible in exactly the place a
reader looks to find out what a result means.

### 13.3 Required and optional inputs

**Excluding a row and declaring the exclusion is not always enough.** If origin filtering
(§3.1) or provider-time resolution (§3.3) removes *every* row of a domain a factor depends on,
the honest outcome is not a smaller factor — it is no factor.

Every query, factor and artifact definition declares each input domain as **REQUIRED** or
**OPTIONAL**:

| | Effect when the domain is emptied |
|---|---|
| **REQUIRED** | **The query, factor or artifact is REFUSED**, with `REQUIRED_INPUT_UNAVAILABLE` naming the domain and the reason it emptied. |
| **OPTIONAL** | Excluded rows are counted and the corresponding limitation token is emitted. Permitted **only** where the definition declares the input optional. |

The worked case the review names: a factor requiring analyst estimates, run under
`PUBLIC_PIT`. Every estimate row is `PROVIDER_DERIVED` and therefore ineligible, so the domain
empties completely. **The factor must refuse.** Computing it anyway would silently produce a
*different factor* — one without an estimates term — under the original factor's name and
version, and nothing downstream would say so.

`ORIGIN_INELIGIBLE_ROWS_EXCLUDED` remains useful evidence, and it is not a substitute for this
rule. It says *some rows went missing*; it cannot say *the thing you computed is not the thing
you named*.

#### The coverage contract — "not completely empty" is not "sufficient"

A required domain that loses 90% of its rows is not satisfied merely by retaining 10%. Every
required input declares the **scope** at which it must be satisfied and the **minimum coverage**
within that scope:

| `coverage_scope` | Satisfied when | Typical use |
|---|---|---|
| `WHOLE_DOMAIN` | the domain has at least `min_rows` admissible rows overall | reference data |
| `PER_SESSION` | every session in the query range meets `min_coverage_fraction` | price bars, universe |
| `PER_SECURITY` | every security in the universe meets `min_coverage_fraction` | fundamentals, estimates |
| `PER_SECURITY_SESSION` | every (security, session) cell required by the factor is present | borrow at signal time |

A required input failing its contract → **refuse** with `REQUIRED_INPUT_UNAVAILABLE`, naming the
scope, the threshold and the observed coverage. An optional input failing its contract →
permitted, counted, token emitted.

The threshold is part of the factor definition and therefore part of
`factor_definition_version`. Changing it changes the factor.

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
