# Phase 3 — Data Quality and Reconciliation Plan

**Status: PROPOSED — planning only. No check is implemented.**

> **Revision 4 (2026-08-26).** Every temporal check now reads one origin-aware
> **`source_anchor`** (§2.1) instead of `public_available_time`, so a `SYSTEM_OBSERVED` or
> `PROVIDER_DERIVED` row can no longer evade a class invariant by having a null public time.
> Six specific conditions are corrected (§4.0.4, provider-before-public, late arrival, backfill,
> the provider-realistic equality case), derived-artifact checks are added (§4.6), and
> required-input completeness is enforced (§4.7).
>
> **Revision 3 (2026-08-26).** Impossibility checks are now **origin-aware** as well as
> class-aware (§4.1): a null `public_available_time` is a defect for an `AUTHORITATIVE_PUBLIC`
> record and correct for a proprietary one. Profile checks are rebuilt around eligibility and
> the withdrawn `DECLARE` resolution (§4.3).
>
> **Revision 2 (2026-08-26).** Review found the blanket rule *"availability before observation
> → BLOCKING"* invalid for facts announced ahead of their effective date — a scheduled
> earnings date or an announced split would have been blocked while being entirely correct.
> Temporal checks are now **class-aware** (§4.1) and every condition is expressed as an exact
> inequality. Leakage and late-arrival are now separate conditions with separate severities
> (§4.2). Profile, revision-view and adjustment checks are new (§4.3–§4.5).

---

## 1. Principle

Data-quality checks in a trading system are not hygiene. They are the mechanism by which a
result is allowed to be *believed*. The posture is inherited from
[ADR-0004](../decisions/ADR-0004-deterministic-order-identity-idempotency-and-execution-lifecycle.md)
§5, which established that missing or corrupt durable state **fails closed** rather than being
read as "nothing happened":

> **A `BLOCKING` data-quality issue open against a dataset makes every research, scanner and
> backtest result that touches it invalid. The result is refused, not annotated.**

Checks are **deterministic**: same inputs, same findings. No sampling, no thresholds tuned by
eye, no model deciding what looks wrong. Findings are stored as `data_quality_issue` rows
([conceptual-schema.md](conceptual-schema.md) §17) so the code that refuses to serve a result
can query them.

## 2. Severity

| Severity | Meaning | Effect |
|---|---|---|
| **INFO** | Observed, expected, recorded for audit. | none |
| **WARNING** | Anomalous. A human should look. Results stay valid but are **labelled**. | annotation on the research manifest |
| **BLOCKING** | The data cannot support a decision. | **every dependent result is refused** |

Two rules keep severity honest:

- **Escalation by accumulation.** A `WARNING` firing on more than a configured fraction of a
  dataset becomes `BLOCKING` for that dataset. One bad bar is an anomaly; ten thousand is a
  broken pipeline wearing an anomaly costume.
- **Suppression is a named human act.** `status = SUPPRESSED` requires `suppressed_by` and
  `suppression_reason`. No bulk suppression, no automatic ageing-out. INC-0001's lesson
  applies: *"the automated path has guardrails; the manual path had none."*

### 2.1 Notation

`pub` = `public_available_time` · `prov` = `provider_available_time` ·
`seen` = `system_first_seen_time` · `ing` = `ingestion_time` · `obs` = `observation_time` ·
`ann` = `announcement_time` · `smp` = `sample_time` ·
`dat(P)` = `decision_available_time` under profile `P` · `build` = dataset build time ·
`origin` = `information_origin` · `elig(P)` = the record is eligible under profile `P` per
[contract §3.1](pit-data-contract.md) · `pub_ub` / `prov_ub` = the public and provider
**upper-bound** fields ([contract §2.6](pit-data-contract.md)).

**`anchor` = `source_anchor(record)`** ([contract §7.1](pit-data-contract.md)):

```
AUTHORITATIVE_PUBLIC -> pub   (else pub_ub)
PROVIDER_DERIVED     -> prov  (else prov_ub)
SYSTEM_OBSERVED      -> seen
DERIVED_ARTIFACT     -> computed from lineage under the requested profile
```

Revision 3 wrote the class invariants against `pub` alone. For a proprietary or
system-observed row `pub` is legitimately null, so **the check silently passed** — a consensus
snapshot stamped before the moment it was sampled would not have been caught. Every temporal
check below reads `anchor`.

**Every inequality below is evaluated only over times the record actually has.** A comparison
against a time a record legitimately lacks is skipped, not failed — that was revision 2's
error, and §4.0 makes the skip explicit rather than implicit.

---

## 3. Structural checks

| # | Check | Condition | Severity |
|---|---|---|---|
| 3.1 | Duplicate records | >1 row for a PK at the same `revision_sequence` | **BLOCKING** |
| 3.2 | Schema drift | vendor payload columns/types differ from the recorded contract | **BLOCKING** |
| 3.3 | Checksum change | a bronze artifact hash differs from the one an `ingestion_run` recorded | **BLOCKING** |
| 3.4 | Unrecognised schema version | in any curated table | **BLOCKING** |
| 3.5 | Missing envelope | `availability_derivation = UNKNOWN` in a PIT query | **BLOCKING** |
| 3.6 | Missing temporal class | any entity with no `temporal_fact_class` | **BLOCKING** |
| 3.7 | Orphan reference | a foreign key with no target | **BLOCKING** |
| 3.8 | Stale ingestion | newest row of a live-facing dataset older than its freshness bound | **BLOCKING** live / **WARNING** research |

---

## 4. Temporal checks

### 4.0 Origin conformance — checked first

These decide which of the later checks even apply. A record failing §4.0 is malformed, and
running §4.1 against it would produce a misleading verdict.

| # | Check | Exact condition | Severity |
|---|---|---|---|
| 4.0.1 | Origin absent or outside the closed vocabulary | `origin ∉ {AUTHORITATIVE_PUBLIC, PROVIDER_DERIVED, SYSTEM_OBSERVED}` | **BLOCKING** |
| 4.0.2 | Public fact with no public time established | `origin = AUTHORITATIVE_PUBLIC` ∧ `pub IS NULL` | **BLOCKING** — this is `UNKNOWN`, not `NOT_APPLICABLE` |
| 4.0.3 | Proprietary fact carrying a public time | `origin = PROVIDER_DERIVED` ∧ `pub IS NOT NULL` | **BLOCKING** — if a public instant exists, the origin is wrong |
| 4.0.4 | Proprietary fact with no provider time **and no configured resolution** | `origin = PROVIDER_DERIVED` ∧ `prov IS NULL` ∧ `prov_ub IS NULL` ∧ dataset resolution ∉ {`EXCLUDE`,`BOUND`,`DOWNGRADE`} | **BLOCKING**. A missing provider time is **not** malformed when a resolution is configured — revision 3 made it so, which would have blocked every legitimately-bounded dataset |
| 4.0.5 | System-observed fact carrying vendor timing | `origin = SYSTEM_OBSERVED` ∧ (`pub IS NOT NULL` ∨ `prov IS NOT NULL`) | **BLOCKING** |
| 4.0.8 | Derived row carrying source times | `origin = DERIVED_ARTIFACT` ∧ (`pub` ∨ `prov` ∨ `seen`) `IS NOT NULL` | **BLOCKING** |
| 4.0.9 | Derived row with incomplete lineage | `origin = DERIVED_ARTIFACT` ∧ (`lineage` empty ∨ any input unresolvable to a published `dataset_version`) | **BLOCKING** |
| 4.0.10 | Bound written into an exact field | `provider_availability_derivation = FIRST_SEEN_UPPER_BOUND` ∧ `prov IS NOT NULL`; or the same for `pub` | **BLOCKING** ([contract §2.6](pit-data-contract.md)) |
| 4.0.11 | Row mixes facts | more than one `temporal_fact_class` or `information_origin` implied by a single row's fields | **BLOCKING** — the atomic-fact rule ([contract §1 R5](pit-data-contract.md)) |
| 4.0.6 | Derivation disagrees with origin | `availability_derivation = NOT_APPLICABLE` ∧ `origin = AUTHORITATIVE_PUBLIC`, or `= UNKNOWN` ∧ `origin ≠ AUTHORITATIVE_PUBLIC` | **BLOCKING** |
| 4.0.7 | Missing `seen` | `seen IS NULL`, any origin | **BLOCKING** |

### 4.1 Impossibility and leakage — class-aware and origin-aware

These say *this could not have happened*, so a violation means a timestamp is wrong, and
serving the row would hand a backtest information nobody had.

| # | Check | Exact condition | Applies to | Severity |
|---|---|---|---|---|
| 4.1.1 | Held before public | `pub IS NOT NULL` ∧ `seen < pub` | all classes | **BLOCKING** |
| 4.1.2 | Held before provider supplied | `prov IS NOT NULL` ∧ `prov` not `FIRST_SEEN_UPPER_BOUND` ∧ `seen < prov` | all classes | **BLOCKING** |
| 4.1.3 | Row written before first seen | `ing < seen` | all classes | **BLOCKING** |
| 4.1.4 | Provider ahead of public **for the same fact** | `origin = AUTHORITATIVE_PUBLIC` ∧ `pub IS NOT NULL` ∧ `prov IS NOT NULL` ∧ `prov < pub` | `AUTHORITATIVE_PUBLIC` **only** | **BLOCKING** — a provider cannot have offered a public fact before it was public; one of the two timestamps is wrong. Revision 3 graded this `WARNING`, which let a contradiction through |
| 4.1.5 | **Retrospective** fact available before it occurred | `anchor < obs` | `RETROSPECTIVE` **only** | **BLOCKING** |
| 4.1.6 | **Announced-forward** fact available before it was announced | `anchor < ann` | `ANNOUNCED_FORWARD` **only** | **BLOCKING** |
| 4.1.7 | **Sampled state** available before it was sampled | `anchor < smp` | `SAMPLED_STATE` **only** | **BLOCKING** |
| 4.1.8 | Revision predates the revision it supersedes | `anchor(rev n) < anchor(rev n−1)` | all | **BLOCKING** |
| 4.1.9 | Future-dated availability | `dat(P) > build` | all | **BLOCKING** |
| 4.1.10 | Estimate snapshot series moving backward | `snapshot_time` order disagrees with `anchor` order (see 4.1.8) | `SAMPLED_STATE` | **BLOCKING** |
| 4.1.11 | DST-ambiguous instant stored unresolved | no offset recorded for a fall-back-hour local time | all | **BLOCKING** |
| 4.1.12 | Session date derived by UTC truncation | `session_date ≠ calendar.session_of(instant)` | bars | **BLOCKING** |

All three class checks read the **same** `anchor` (§2.1), so a `SYSTEM_OBSERVED` row is held to
`seen >= sample_time` exactly as an `AUTHORITATIVE_PUBLIC` row is held to
`pub >= observation_time`. **No origin evades its class invariant by having a null public
time** — which is what revisions 2 and 3 both allowed.

> **There is deliberately NO check of the form `effective_date < pub`.** For
> `ANNOUNCED_FORWARD` facts an effective date later than availability is the normal, correct
> case — that is the entire class. Revision 1's blanket rule is retired, and §6.1's
> negative-control fixtures exist to prove it stays retired.

### 4.2 Latency — separate from leakage, and never confused with it

Leakage is impossible. Lateness is merely inconvenient — unless something live depends on it.

| # | Check | Exact condition | Severity |
|---|---|---|---|
| 4.2.1 | Late arrival, **public fact** | `origin = AUTHORITATIVE_PUBLIC` ∧ `seen − pub > latency_budget(dataset)` | **WARNING** |
| 4.2.1a | Late arrival, **proprietary fact** | `origin = PROVIDER_DERIVED` ∧ `seen − prov > latency_budget(dataset)` | **WARNING** |
| 4.2.1b | Late arrival, **system-observed** | **not applicable** — there is no external delivery to be late. `ing − seen > write_budget` is checked instead, as a pipeline-health signal | **INFO**, escalating |
| 4.2.2 | Live freshness breach | dataset is live-facing **and** `now − seen > freshness_bound(dataset)` | **BLOCKING** |
| 4.2.3 | Borrow staleness | `as_of − smp > borrow_freshness_bound` | **BLOCKING** |
| 4.2.4 | Backfill detected | an `ingestion_run` delivered rows whose **valid-time coverage** (`observation_time` / `effective_date` / `sample_time`) extends earlier than the prior run's minimum for that dataset, **or** whose `anchor` predates it | **INFO** — and sets `is_backfill`, which §4.3 then polices |

Revision 3 detected backfills through `pub` alone, so a backfill of proprietary or
system-observed rows — precisely the ones whose provider timing is least trustworthy — was
invisible. Detection is now origin-aware and keyed on **coverage plus anchor**, so it fires
whatever kind of row arrived.

### 4.3 Information-set profile

| # | Check | Exact condition | Severity |
|---|---|---|---|
| 4.3.1 | Mixed profiles in one result | >1 distinct `information_set_profile` resolved within a result set | **BLOCKING** |
| 4.3.2 | Unresolved provider availability | profile = `PROVIDER_REALISTIC_PIT` ∧ `prov IS NULL` ∧ dataset resolution ∉ {`EXCLUDE`,`BOUND`,`DOWNGRADE`} | **BLOCKING** |
| 4.3.3 | **Public timing substituted for absent provider timing** | profile = `PROVIDER_REALISTIC_PIT` ∧ `prov IS NULL` ∧ `prov_ub IS NULL` ∧ the row was nevertheless served, governed by `pub` — the withdrawn `DECLARE` behaviour | **BLOCKING** |
| 4.3.4 | Undeclared provider gap | resolution = `BOUND` ∧ manifest lacks `PROVIDER_AVAILABILITY_UNKNOWN`; or resolution = `DOWNGRADE` ∧ manifest lacks `PROFILE_DOWNGRADED_TO_PUBLIC` | **BLOCKING** |
| 4.3.5 | Ineligible row served | a row served under a profile its `origin` is ineligible for (§4.0, [contract §3.1](pit-data-contract.md)) | **BLOCKING** |
| 4.3.6 | Undeclared exclusions | rows were excluded for ineligibility ∧ manifest lacks `ORIGIN_INELIGIBLE_ROWS_EXCLUDED` | **BLOCKING** |
| 4.3.7 | Profile ordering violated | for a record **eligible under both compared profiles**: `dat(PUBLIC_PIT) > dat(PROVIDER_REALISTIC_PIT)` ∨ `dat(PROVIDER_REALISTIC_PIT) > dat(FORWARD_SYSTEM)` | **BLOCKING** |
| 4.3.8 | Ordering asserted across an ineligible profile | the ordering check ran on a record not eligible under both sides | **BLOCKING** — a malformed comparison, not a data defect |
| 4.3.9 | Backfill admitted too early | row admitted at `as_of` while `dat(P) > as_of` under the declared profile | **BLOCKING** |
| 4.3.10 | `BOUND` applied to a system-observed row | resolution = `BOUND` ∧ `origin = SYSTEM_OBSERVED` | **BLOCKING** — bounding a provider time that does not exist invents one |
| 4.3.11 | Downgrade not carried through | `resolved_profile ≠ requested_profile` ∧ any artifact key, dataset version or `run_id` still names `requested_profile` | **BLOCKING** ([contract §13.2](pit-data-contract.md)) |

**4.3.3 is deliberately narrow.** When `max(pub, prov)` legitimately equals `pub` — because the
provider offered the row at the same instant it became public, or earlier-but-invalid per
4.1.4 — that is a correct governing time and **not** a violation. Revision 3's wording would
have blocked it for resembling the withdrawn behaviour. What is forbidden is *substitution*:
serving a row on public timing **because provider timing is absent**.

### 4.4 Revision view

| # | Check | Exact condition | Severity |
|---|---|---|---|
| 4.4.1 | Non-PIT view in research | `revision_view = LATEST_RESTATED` reached from a research or backtest path | **BLOCKING** (also a static-test failure) |
| 4.4.2 | Incomplete chronology undeclared | `revision_chronology_completeness ≠ COMPLETE` ∧ view = `AS_KNOWN_AT_AS_OF` ∧ manifest lacks `REVISION_CHRONOLOGY_INCOMPLETE` | **BLOCKING** |
| 4.4.3 | Revision sequence gap | sequences present are not contiguous from 0 | **WARNING** — signals missing intermediate revisions |
| 4.4.4 | Restatement with no filing anchor | `revision_sequence > 0` ∧ `filing_id IS NULL` | **WARNING**, escalating |

### 4.5 Adjustment

| # | Check | Exact condition | Severity |
|---|---|---|---|
| 4.5.1 | Cache does not reproduce | recomputed series hash ≠ `adjusted_bar_artifact.content_hash` | **BLOCKING** |
| 4.5.2 | Action applied before ex-date | adjustment applied to a bar with `session_date < action.ex_date` | **BLOCKING** |
| 4.5.3 | Inadmissible action applied | adjustment used an action with `dat(P) > as_of_epoch` | **BLOCKING** |
| 4.5.4 | Unkeyed adjusted series | an adjusted series exists outside `adjusted_bar_artifact` | **BLOCKING** |

---

### 4.6 Derived artifacts

| # | Check | Exact condition | Severity |
|---|---|---|---|
| 4.6.1 | Availability not equal to lineage max | `dat(artifact, P) ≠ max over inputs of dat(input, P)` for `P ∈ {PUBLIC_PIT, PROVIDER_REALISTIC_PIT}` | **BLOCKING** |
| 4.6.2 | Forward availability ignores build time | `dat(artifact, FORWARD_SYSTEM) < artifact_first_built_time` | **BLOCKING** |
| 4.6.3 | Eligibility wider than lineage | artifact served under a profile any input is ineligible for | **BLOCKING** |
| 4.6.4 | Rebuild rewrote history | `artifact_first_built_time` changed while `lineage` and `derivation_spec_version` are unchanged | **BLOCKING** |
| 4.6.5 | Silent lineage change | `lineage` or `derivation_spec_version` changed without a new artifact key and hash | **BLOCKING** |
| 4.6.6 | Artifact does not reproduce | recomputation from `lineage` + `derivation_spec_version` ≠ `artifact_content_hash` | **BLOCKING** |

4.6.4 and 4.6.5 are the pair that keeps rebuilds honest: recomputing a value we already had
must not move when we had it, and consuming different inputs must not reuse the same identity.

### 4.7 Required-input completeness

Excluding rows and declaring the exclusion is evidence, not sufficiency
([contract §13.3](pit-data-contract.md)).

| # | Check | Exact condition | Severity |
|---|---|---|---|
| 4.7.1 | Required domain emptied | a domain declared **REQUIRED** by the factor/query/artifact definition has zero admissible rows after origin filtering and provider-time resolution | **BLOCKING** — refuse with `REQUIRED_INPUT_UNAVAILABLE` |
| 4.7.2 | Required domain partially emptied beyond tolerance | admissible rows < the definition's declared minimum coverage | **BLOCKING** |
| 4.7.3 | Optional exclusion undeclared | an **OPTIONAL** domain lost rows ∧ counts absent from the manifest ∧ its limitation token absent | **BLOCKING** |
| 4.7.4 | Silent substitution | a factor computed with a required input missing, under the same `factor_definition_version` | **BLOCKING** — it is a different factor wearing the same name |

The worked case: a factor requiring analyst estimates, run under `PUBLIC_PIT`. Every estimate
row is `PROVIDER_DERIVED` and therefore ineligible, so the domain empties entirely. **4.7.1
refuses.** Computing the factor anyway would publish a different quantity under the original
name and version, and nothing downstream would say so.

## 5. Market-data checks

| # | Check | Condition | Severity |
|---|---|---|---|
| 5.1 | Impossible OHLC | `high < low` ∨ `open ∉ [low,high]` ∨ `close ∉ [low,high]` | **BLOCKING** |
| 5.2 | Non-positive price / negative volume | `price <= 0` ∨ `volume < 0` | **BLOCKING** |
| 5.3 | Missing session | calendar session with no bar for a listed, unhalted security | **WARNING**, escalating |
| 5.4 | Missing bar in a listed range | universe member with no bar that session | **WARNING**, escalating |
| 5.5 | Split discontinuity | close-to-close move beyond bound with no `corporate_action` explaining it | **BLOCKING** |
| 5.6 | Adjusted/unadjusted mismatch | recomputed adjusted ≠ an independently adjusted reference, beyond tolerance | **BLOCKING** |
| 5.7 | Zero volume on a regular session | for a liquid universe member | **WARNING** |
| 5.8 | Implausible price band | outside a rolling-window bound | **WARNING** |

Check 5.5 catches unrecorded corporate actions — the failure that silently destroys momentum
factors, because an unadjusted split looks exactly like a −50% return.

## 6. Identity and universe checks

| # | Check | Condition | Severity |
|---|---|---|---|
| 6.1 | Ticker-history overlap | one ticker → two `security_id` on one date | **BLOCKING** |
| 6.2 | Ticker gap | listed security with no ticker inside its listing range | **BLOCKING** |
| 6.3 | Survivorship leakage | a historical universe snapshot in which **no** member has since delisted | **BLOCKING** |
| 6.4 | Delisted absence | zero delisted securities across all historical snapshots | **BLOCKING** |
| 6.5 | Universe rebuild drift | rebuild from same inputs + rule version + profile yields different membership | **BLOCKING** |
| 6.6 | Eligibility from inadmissible data | any evaluation input with `dat(P) > session_date` | **BLOCKING** |
| 6.7 | Security-type leakage | non-common-stock in a common-stock universe | **BLOCKING** |
| 6.8 | Profile-free universe | a `universe_membership` row with no `information_set_profile` | **BLOCKING** |

Checks 6.3 and 6.4 are deliberately crude, and that is the point: they are the smoke alarm for
the defect that is otherwise invisible. If a 2012 snapshot contains no company that has since
disappeared, the data is not historical, whatever the vendor calls it.

## 7. Cross-provider reconciliation

| # | Check | Severity |
|---|---|---|
| 7.1 | Price disagreement beyond tolerance | **WARNING**, escalating |
| 7.2 | Security-master disagreement (delisting, ticker change, listing date present in one and absent in the other) | **WARNING**, escalating to **BLOCKING** on systematic divergence |
| 7.3 | Corporate-action disagreement (ratio or ex-date) | **BLOCKING** |
| 7.4 | Calendar disagreement between independent calendar sources | **BLOCKING** |
| 7.5 | Fundamental disagreement for the same metric, period and filing | **WARNING**, escalating |
| 7.6 | Conflicting publication timestamps | **WARNING**; the later time is used ([contract §12.5](pit-data-contract.md)) |

**Disagreement is never resolved by silently preferring one source.** Either a documented
precedence rule applies and is recorded in the manifest, or the row is quarantined. Two
sources that disagree are two claims, and picking the convenient one is how a data platform
starts lying quietly.

### 7.1 Cross-checking depends on holding two licences

Revision 1 assumed a free second source. That assumption is corrected in
[provider-evaluation.md](provider-evaluation.md): a broad local cross-check generally requires
a **second paid dataset**. Where only one source is licensed, the affected §7 checks are
**not run**, and every dependent result carries `SINGLE_SOURCE_UNVERIFIED`. A check that
cannot run is declared, never quietly skipped.

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

- The PIT query layer consults open `BLOCKING` issues before serving, and raises.
- A backtest cannot start with one open.
- A research manifest **cannot be produced** for such a run — so a result that would be
  invalid also cannot be made to look reproducible.
- Scanner output produced while one is open is not presented as valid.

This mirrors the Phase-2 preflight, which exits non-zero and stops a deployment before a
container starts rather than warning inside one.

## 9. Reporting

- Every ingestion run emits a quality report: checks executed, findings by severity, checks
  **not** run and why, and the datasets now gated.
- **Silent truncation is forbidden.** If a check samples, bounds or skips anything, the report
  says what it skipped. A check that quietly covered less than it claims is worse than no
  check, because it converts an unknown into a false assurance.
- Reports contain **no** brokerage identifiers, account-binding digests or credentials
  (CLAUDE.md §3). The data platform has no reason to know they exist.
- **Quality reports derived from subscribed vendor data stay under `.runtime/` and are not
  committed** while the repository is public and the licensing questions in
  [provider-evaluation.md](provider-evaluation.md) remain unresolved. An empirical evaluation
  of a vendor's data is itself derived from that data.
