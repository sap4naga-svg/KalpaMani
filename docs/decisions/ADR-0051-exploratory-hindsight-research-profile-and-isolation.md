# ADR-0051 — An exploratory hindsight research profile, kept apart from production qualification

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0051 is proposed and carries no authority.
That is a statement about the present, it will remain true of these days after any later merge, and it
is not to be rewritten as though this decision had authority before it was accepted. On merge, this ADR
becomes **ACCEPTED / IN FORCE** as **the research-only vocabulary of §2, the distinction of §2.2, the
declared limitations of §2.3, the non-satisfaction rule of §2.4, and the isolation contracts of §3 — and
nothing else**, effective together with the offline contracts merged beside it. **Acceptance authorizes
no execution and grants no permission** (§5): no acquisition, no image build or publication, no Terraform
plan or apply, no AWS or provider request, no research run, no backtest, no bridge from production Gold,
no benchmark, no compute and no spend. The decisions §6 lists stay **pending** on merge and after it.

## 1. Context

The production data plane resolves availability under `PROVIDER_REALISTIC_PIT` with exactly two
derivations (ADR-0035 §3.3, `kalpamani.data.production.sharadar.availability`): **P-2**,
`FIRST_SEEN_UPPER_BOUND` — a row version is available from the retrieval instant of the acquisition that
made its bytes current; and **P-3**, `DELIVERY_WINDOW` — from the instant of an explicit per-version
delivery record. The vendor-date and archival-capture routes are gated and refused. A decision at
session `d` consumes only versions bounded at or before `min(decision_time(d), as_of)`.

The consequence ADR-0035 §3.3 states in terms — *a backtest over sessions before the first ingestion
admits nothing under P-2* — was traced through the code on 2026-09-15: a bar for a 2019 session
retrieved in 2026 is bounded in 2026, every historical `tickers` attribute is today's value (the vendor
publishes the latest venue and no dated series), and no per-version delivery record exists for any past
date. So **no historical simulation is reachable under the accepted contracts from this provider**, by
either route, and the accepted research horizon begins at the first production acquisition and grows
forward. That is correct, and it is not a defect.

The owner nevertheless needs a way to screen the research-stage Breakout Long module against history
before years of forward accumulation exist. The only honest way is a **separate research mode** that
*assumes* historical availability, says so on every artefact, and can never be mistaken for — or
consumed as — production-qualified evidence.

## 2. Decision — the research-only vocabulary

### 2.1 Two research-only members, in their own vocabulary

`kalpamani.data.exploratory.vocabulary` defines **`ExploratoryProfile.EXPLORATORY_HINDSIGHT`** and
**`ExploratoryDerivation.AS_DATED`**. They are **not** members of the accepted `InformationSetProfile`
or `ProviderBoundDerivation`, which stay closed and unchanged; the module refuses to import if either
value ever overlaps an accepted one. Because every accepted result type validates its profile against
the accepted enumeration, an exploratory profile **cannot be carried by an accepted result, cannot
reach the accepted Brain gate, and cannot be resolved by the accepted production build** — by type,
not by convention.

`AS_DATED` assumes: a bar was knowable at its own session close; a `tickers` attribute at all times;
an action at its date's session open.

### 2.2 Assumed availability is not evidenced availability

Production P-2/P-3 record availability that was **observed** (a retrieval instant) or **evidenced** (a
delivery record). `AS_DATED` records availability that is **assumed** from the row's own date. An
exploratory document carries `availability_basis = ASSUMED_HISTORICAL` and can carry nothing else —
`EVIDENCED` exists in the vocabulary only so that an attempt to claim it is refused by name. **Nothing
in this ADR changes, relaxes or reinterprets P-2 or P-3**: the production resolution policy
(`sharadar-availability-v2`), its two expressible derivations and its `PROVIDER_REALISTIC_PIT` profile
are unchanged and are held so by test.

### 2.3 The declared limitations

Every exploratory publication declares its limitations as closed members. Four follow from
`AS_DATED` itself and are **mandatory**: **`REVISION_LOOKAHEAD`** (today's row version stands in for
every historical version; corrections and re-adjustments are invisible), **`CURRENT_ATTRIBUTE_LOOKAHEAD`**
(today's exchange, category and listing attributes stand in for every past session),
**`TERMINAL_VALUATION_OPTIMISTIC`** (a delisted position is valued at its last available close — an
optimistic valuation, never a fill and never knowable in advance), **`NO_INTRADAY_INSTANT`**
(date-granular data establishes no intraday instant). Two are declared when the pending decisions of §6
make them apply: **`EVENT_BLIND`** (no scheduled-event evidence exists) and
**`BENCHMARK_SELF_REFERENCE`** (a benchmark built from the universe itself). A consumer must acknowledge
every limitation its inputs declare, or it is refused.

### 2.4 What an exploratory result never satisfies

An exploratory publication carries `production_qualification = NONE`, and the contract admits no other
value. **No exploratory result satisfies P1–P9, any G2 criterion (ADR-0035 G2-A…G2-H), any provider
qualification, or any promotion criterion of the equity evaluation protocol (§10): promotion requires a
locked final window on qualified data, which an exploratory run cannot supply.** An exploratory result
is a screening disposition and hypothesis evidence, classified `LICENSED_DERIVED`, kept inside the
private boundary, and never a production rule, a Cockpit `AVAILABLE` figure or a point-in-time claim
about any period.

### 2.5 The accepted strategy thresholds are untouched

The eleven Breakout Long parameters, its `StrategySpec` (`breakout-long/r1-research`, requiring
`PROVIDER_REALISTIC_PIT`), its holding horizon and its adjustment convention are unchanged. A research
specification that consumes exploratory inputs is a **different, explicitly derived** specification
that enumerates every difference from the accepted one (§3.3).

## 3. Decision — the isolation contracts (implemented offline beside this ADR)

`kalpamani.data.exploratory.contracts` and `kalpamani.data.exploratory.admission` define four closed,
versioned documents, each parsed totally (a missing, unknown, duplicate, wrong-typed, production-valued,
mixed or contradictory field is a closed `ExploratoryDefect`, never a default and never a raw exception)
and each round-tripping exactly through `document()` / `parse_*`:

| contract | identifies |
|---|---|
| `kalpamani-exploratory-provenance/v1` | the profile, derivation, assumed basis, declared limitations, the production build manifest the publication derives from (by digest), and the qualification claim `NONE` |
| `kalpamani-exploratory-publication/v1` | one derived publication: identity, content digest, classification `LICENSED_DERIVED`, provenance |
| `kalpamani-exploratory-input-set/v1` | the publications one research run consumes together — one profile, one derivation, one limitation set, or `PROVENANCE_MIXED` |
| `kalpamani-research-specification/v1` | the explicit opt-in: the profile and derivation it admits, the limitations it acknowledges, the accepted strategy version it derives from, every difference, and its trial number |

### 3.1 Substitution is refused by name

A production profile (`PUBLIC_PIT`, `PROVIDER_REALISTIC_PIT`, `FORWARD_SYSTEM`) or derivation
(`FIRST_SEEN_UPPER_BOUND`, `DELIVERY_WINDOW`, `NONE`) appearing where the research-only value belongs is
`PRODUCTION_PROFILE_SUBSTITUTED` / `PRODUCTION_DERIVATION_SUBSTITUTED` — distinct from an unknown value,
so a relabelling attempt is visible as one. `EVIDENCED_BASIS_CLAIMED` and `QUALIFICATION_CLAIMED` are
likewise named refusals.

### 3.2 Admission: one consumer kind, exact type, fail closed

`admit(consumer, inputs)` returns `ADMITTED` only when `consumer` is exactly a `ResearchSpecification`
whose profile and derivation are the input set's and whose acknowledged limitations cover the set's.
**Any object carrying an accepted `required_profile`** — the enumeration member or its exact name as a
string, directly or under `data` — the accepted `StrategySpec` of Breakout Long first among them — is
`REFUSED_PRODUCTION_CONSUMER`; anything else is `REFUSED_NOT_A_RESEARCH_SPECIFICATION`; a lookalike with
the right attributes but the wrong type is refused; inspection that raises at any attribute is refused,
and `admit` never raises. There is no duck-typed opt-in.

### 3.3 A research specification is derived, versioned and counted

It names its `base_strategy_version`, enumerates at least one difference, acknowledges **at least the
four mandatory limitations** (a specification that ignores one could never consume anything and would
read as unawareness — it is refused at construction, `LIMITATION_MISSING`), and carries a trial number;
its digest is the parameter identity a trial ledger records. A research specification identical to its
base would be the base, and is refused.

### 3.4 The isolation direction is structural

No module under `kalpamani.data.contracts`, `curate`, `pit`, `production`, `qualify`, `quality`,
`ingest`, `storage`, `kalpamani.strategies`, `execution`, `portfolio`, `risk`, `broker`, `common` or
`scripts/` imports `kalpamani.data.exploratory`; the exploratory package imports no production runtime,
no SDK and no network module. A static test holds both.

### 3.5 What the contracts do not claim

They are labelling and admission contracts, **not cryptographic ones**. An owner who rewrites the entire
private evidence chain consistently can make an exploratory publication say anything. What they guarantee
is narrower and is what matters: nothing *accidental* — a wrapper, a bridge, a parser default, a copied
field — can relabel exploratory evidence as production-qualified, and no accepted consumer can take it
without an explicit, refusable opt-in.

## 4. What this ADR does not decide or implement

**Not implemented, not designed by this ADR**: the bridge from production Gold (ADR-0040 manifest and
objects) to any exploratory publication; the exploratory membership and availability resolution; a
benchmark; a backtest runner; a portfolio ledger; a report; any research-mode gate. Each is a later
slice under its own authorization, reviewed against the M0 research specification the owner holds
outside this repository, and none is implied by accepting this ADR.

> **HISTORICAL — the state as of the pull request that introduced this ADR, superseded in part by
> §9 (2026-09-15).** A later, separately authorized slice implemented the exploratory resolution, a
> Silver-to-exploratory bridge, benchmark A, the M0 runner, two terminal ledgers and a report,
> **offline and on synthetic fixtures only**. The text above records what this ADR itself decided and
> implemented, and it is not rewritten; what §9 records is a later event, and it changes neither the
> status of this ADR nor the decisions §6 keeps pending.

## 5. Acceptance and execution authority are separate

**Acceptance** (the merge of this ADR's pull request) establishes the vocabulary and the contracts and
nothing else. **Execution authority** — to acquire the data window, to build or publish any image, to
run any exploratory computation, to read any licensed object, to spend anything — is a separate written
authorization per action that this ADR neither grants nor implies, exactly as every prior ADR's
acceptance has been kept apart from its execution. Implementing the contracts beside this ADR ran no
computation on any row: the tests use synthetic documents only.

## 6. Decisions explicitly pending (not taken by this ADR, not implied by its acceptance)

| pending | status |
|---|---|
| whether an exploratory mode is wanted at all (O-1) | **pending** |
| the benchmark — a universe-derived index or a fund series under a G1 amendment (O-2) | **pending**; `BENCHMARK_SELF_REFERENCE` is declared only if the first is chosen |
| the acquisition route — bounded runs under the accepted request form or a bulk-acquisition ADR (O-5) | **pending**; no acquisition is authorized |
| the research compute location (O-6) | **pending**; no compute exists |
| exit rule, costs, sizing policy, terminal accounting, the data window, the acknowledgment that no untouched test window exists (O-3, O-4, O-7…O-11) | **pending** |
| Decision D-1 (ADR-0050 §2.11) | **undecided**; the rehearsal path stays CLOSED |

## 7. Consequences

- The accepted vocabularies, the Brain gate's admitted profiles, the production availability policy and
  the accepted Breakout Long specification are unchanged, and tests assert each.
- A future research runner has a closed input contract to consume and a closed admission rule to pass,
  and cannot be handed production evidence by mistake or exploratory evidence without an opt-in.
- Every exploratory artefact says on its face what it assumed and what it does not claim.
- G2 stays OPEN, CONTROL stays DEFERRED, Phase 3 stays NOT COMPLETE, backtesting stays NOT STARTED,
  live trading stays HARD-DISABLED. Nothing was run to produce this decision.

## 8. Review correction 1 (2026-09-15, within the open pull request)

Independent review of the submitted head `56556d9e3d823323c8124913d0754b9d0b0af7d3` found that §3's
"never a raw exception" and §3.2's "inspection that raises is refused" did not hold everywhere, and that two
admission labels and one schema check were weaker than stated. Each was **reproduced on that head by a
regression before it was corrected**, beside a valid control (`tests/unit/test_exploratory_isolation_correction_1.py`):

| finding on 56556d9e | correction |
|---|---|
| a consumer whose `data` attribute raised propagated a `RuntimeError` out of `admit` | every attribute access in the production-consumer inspection is guarded; `admit` never raises |
| a consumer carrying a production profile **by name** (`"PROVIDER_REALISTIC_PIT"` as a string) was refused under the generic code, under-reporting the attempt | the exact accepted name as a string is a production consumer, `REFUSED_PRODUCTION_CONSUMER` |
| a non-string identifier or digest passed straight to a constructor reached `re.fullmatch` and raised `TypeError` | constructors reuse the parsers' typed grammar checks: `FIELD_MALFORMED` |
| a wrong-typed `provenance` on a publication was labelled `PROFILE_MISSING` | `None` is `PROFILE_MISSING`; any other wrong type is `FIELD_MALFORMED` |
| an unhashable item in a limitations list reached `set()` and raised `TypeError` | items are typed before any set is built (one shared `parse_limitations`) |
| `schema_version` accepted `true` and `1.0` for `1` (Python equality) | exact `int`, not `bool`, equal to 1: `CONTRACT_MISMATCH` |
| a lone-surrogate string raised `UnicodeEncodeError` before any refusal | `DOCUMENT_MALFORMED` |
| a research specification could be constructed and parsed without acknowledging a mandatory limitation | refused at construction and at parsing, `LIMITATION_MISSING` (§3.3) |

No refusal code was added or removed; the exact-type opt-in, the production isolation and every pending
decision (§6) are unchanged; the accepted vocabularies, gate, availability policy and Breakout Long
thresholds are untouched. The status of this ADR is unchanged: proposed, no authority while the pull
request is open.

## 9. Slice 2 — the synthetic end-to-end M0 path (2026-09-15, a later and separately authorized slice)

**This section records an implementation event; it records no acceptance event and takes no decision.**
The status line of this ADR is unchanged by it. Recording whether the acceptance clause above has been
satisfied by a merge is a status synchronization the owner directs separately; this slice did not
perform it and does not anticipate it.

Under a written authorization limited to **repository implementation and synthetic testing**, the
components §4 named as not implemented were written **offline, on synthetic fixtures only**, in the
same research-only package:

| component | module | what it does and does not do |
|---|---|---|
| exploratory availability and membership resolution | `kalpamani.data.exploratory.resolution` | `resolve_as_dated` assigns every Silver row an `ExploratoryAvailability` (`EXPLORATORY_HINDSIGHT` / `AS_DATED` / `ASSUMED_HISTORICAL`) whose governing time is the close of the bar's own session, the open before a listing, or the open on or after an action date. It is **not** an `Availability` of the accepted vocabulary, it derives no P-2 or P-3 bound, and the accepted `build_universe` refuses its layer by exact type. `decide_membership` re-uses the accepted universe indexing and decision clauses unchanged, with 252 history sessions and the M0 §14 floors, and a conformance test holds it equal to the accepted build under equal bounds |
| the Silver-to-exploratory bridge | `kalpamani.data.exploratory.dataset` | `ExploratoryDataset` and `publish` produce an `ExploratoryPublication` carrying the mandatory limitations, the qualification claim `NONE` and a content digest; they **never** produce a `VerifiedPublication`. The bridge consumes a `SilverLayer` object; **no bridge reads production Gold objects or an ADR-0040 manifest from any store**, and none is implemented |
| benchmark A | `kalpamani.data.exploratory.dataset.build_benchmark_a` | `M0-EW-UNIVERSE`: the equal-weighted return of the members decided at the previous session's decision instant, so no session's return selects its own membership; a missing bar is a zero return (optimistic) or a total loss (loss ledger). `BENCHMARK_SELF_REFERENCE` is declared. This is the **synthetic fixture's** benchmark, not an O-2 selection |
| the M0 runner | `kalpamani.data.exploratory.m0` | `run_m0` admits only `breakout-long-m0-exploratory-v1` (derived from `breakout-long/r1-research`, D1–D11 recorded), evaluates the unchanged Breakout Long module at the signal instant, executes at the following open with the M0 §14 execution layer (final-fill rejection preserving both sizing limits, prior-session ADDV only, deterministic exit and ranking precedence, causal terminal recognition), and produces two reconciled terminal ledgers (`optimistic`, `total_loss`), the B0 baselines, the cost and idle sensitivities, independent development and validation initialization and a frozen trial digest. `M0_SYNTHETIC_FIXTURE` carries the §14 settings **as a synthetic fixture, not as owner selections**; a `REAL` data kind is refused unless the configuration is `OWNER_SELECTED` with every O-1…O-11 selection recorded — there is no fallback |
| the report | `kalpamani.data.exploratory.report` | a Markdown and JSON rendering labelled `SYNTHETIC / EXPLORATORY_HINDSIGHT`, opening with the bias statement and the D1–D11 differences |

**What the slice establishes, and what it does not.** The synthetic fixture (`tests/fixtures/m0_exploratory.py`)
exercises entries, stop and time exits, constraint skips, a missing bar, a split and a delisting; the
integration tests (`tests/unit/test_m0_exploratory_path.py`) demonstrate the distinct membership, signal
and execution instants, the prior-session ADDV invariance, the final-fill rejection without resizing, the
deterministic precedence and ranking, the causal terminal recognition, the two reconciled ledgers, the
independent initialization with a frozen trial digest, the benchmark's independence from same-session
returns, the continued refusal of every production consumer, and identical repeated runs. **Every figure is
synthetic; a passing synthetic run establishes software behaviour only** — no strategy performance, no
point-in-time qualification, no P1–P9 result, no G2 criterion and no promotion criterion. **Nothing was run
on licensed data, no acquisition occurred, no image was built or published, no AWS, Terraform or provider
request was made, and no broker activity occurred.** The accepted Brain gate, the accepted Breakout Long
thresholds, production P-2 and P-3, D-1 and the closed rehearsal path are unchanged, and tests assert each.

**One guard admission, carrying this ADR's authority and no more.** The vendor-name boundary guards
(`test_sharadar_provider_boundary.py`, `test_sharadar_qualification_boundary.py`) admit
`kalpamani.data.exploratory` as a **fourth** vendor-scoped package, because the research path reads the
accepted Sharadar-shaped Silver, session and universe contracts unchanged and keeps the accepted
`sharadar:<permaticker>` identity rather than re-implementing either. The admission is recorded in the
guards with its reason, a fifth package still fails, the package may still reach no runtime, store,
binding, SDK or network, and no accepted module imports it. Like the A1-surface admission slice 1 made,
it is a guard change made under a PROPOSED ADR and stands or falls with it.

**What stays pending after this slice.** Every decision §6 lists (O-1…O-11, D-1); the bridge from real
production Gold objects; the acquisition of any data window; any real-data execution, which requires an
explicit, validated `OWNER_SELECTED` configuration and its own written authorization; and the status
synchronization that would record this ADR's acceptance event, which is the owner's.
