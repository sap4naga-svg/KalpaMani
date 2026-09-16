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

**The condition above has since been satisfied.** **PR #111 merged** — merged **2026-09-16T02:10:11Z**,
merge commit **`bc16801efbfd9d8c5a9b947f888da64d7dadf72a`**, ordered parents **`21fa654e2d5e76b29f219a0f107dc5532b017ee9`** then
**`56871f69f1e4443b638bf9da7c64f21f9ddafbbd`** (the reviewed head, after the review correction recorded in §8), with a
**merge tree identical to the reviewed pull-request head tree** (`ef15b5dabfdf4065aeed3aabc6f6f37918a9df18`). ADR-0051 is
therefore **ACCEPTED / IN FORCE** exactly as the clause above states — the research-only vocabulary of §2, the
distinction of §2.2, the declared limitations of §2.3, the non-satisfaction rule of §2.4 and the isolation contracts
of §3, effective together with the offline contracts merged beside it, and nothing else. While the pull request was
open it was proposed and carried no authority — true then, and not rewritten. **Acceptance selected none of O-1…O-11,
authorized no real-data run, no acquisition, no image build or publication, no Terraform plan or apply, no AWS or
provider request, no compute and no spend**, and it implies nothing about any later pull request: the synthetic M0
path of §9 and its correction of §10 are carried by **PR #112, which is OPEN and unmerged**, and acceptance of this
ADR is not acceptance of that pull request. The decisions §6 lists stay **pending**. This paragraph was written by
the correction cycle §10 records, under an authorization that directed the acceptance event to be recorded; the
slice §9 records had been directed not to record it, which is why §9 says so and is not rewritten.

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
satisfied by a merge was a status synchronization the owner directed separately; this slice did not
perform it and did not anticipate it. *(The owner has since directed it, and the correction cycle of §10
recorded the acceptance event in the paragraph following the status line.)*

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
it was a guard change made under a then-PROPOSED ADR and stands or falls with it *(the ADR has since been
accepted; see the paragraph following the status line)*.

**What stays pending after this slice.** Every decision §6 lists (O-1…O-11, D-1); the bridge from real
production Gold objects; the acquisition of any data window; any real-data execution, which requires an
explicit, validated `OWNER_SELECTED` configuration and its own written authorization; and the status
synchronization that would record this ADR's acceptance event, which is the owner's.

## 10. Review correction 1 of the synthetic M0 path (2026-09-16, within open PR #112), and the acceptance record

Independent source review of the PR #112 head `ce1f793b9ca4205c56a1ff04026d38cee14c7f2c` raised six findings
against the synthetic M0 path of §9. **Targeted regressions were written first**
(`tests/unit/test_m0_exploratory_correction_1.py`, 41 tests, with the fixture extended by five scenarios) and run
against that head before any correction: **40 failed there and 1 passed** — the passing one
(`test_f1_split_adjusted_volume_preserves_addv`) proves an invariance that held on both bases by construction, and
it is kept as a control. Every other regression passes only after the correction.

| finding on ce1f793b | reproduced by | correction |
|---|---|---|
| **1 — inconsistent split bases.** Execution read bars adjusted through the dataset's *final* session while signal levels were stated on the signal session's basis, so a split effective after a trade reached back into it (a later 2:1 split turned a completed trade into `SKIPPED_ZERO_QUANTITY`), a split between signal and execution manufactured a gap and an incompatible stop, and a split during a holding was silently ignored | `test_f1_*` (4 tests, 5 cases) | execution reads every bar on its **own** session's basis (`ExploratoryDataset.raw_bars`); a level stated on the signal session is carried to the executing session by `split_factor_between`; a split effective while held rescales shares and stop at that open, settles the fractional share in cash at that session's close (`SplitEvent.cash_in_lieu`, no commission — the explicit fractional-share policy), leaves entry facts and planned risk unchanged, and is recorded on the trade and in the journal; ADDV stays basis-invariant *(the settlement's timing and missing-close behaviour were corrected again in §11: the close is read at the close, never at the open)* |
| **2 — entries in the purge / tail.** The loop admitted an entry whenever the *previous* session was in the evaluation window, so a signal on the last development or validation session opened a position at the first purge or tail open | `test_f2_*` | an entry executes only when the signal session **and** the executing session are in the evaluation window; positions still exit there, attributed to the originating window |
| **3 — same-session re-entry.** A security exited at an open (stop, time or terminal) could be re-entered at that same open | `test_f3_*` | securities exited during the session are tracked; a candidate among them is `SKIPPED_EXITED_THIS_SESSION`; ordinary re-entry on a later eligible session is unchanged (ZZRR) |
| **4 — untyped configuration and incomplete trial binding.** Owner selections were a free-text mapping checked for truthiness; no setting was type-, finiteness- or range-checked; a malformed data kind bypassed the REAL check; `history_sessions` was an override parameter; the trial digest bound the calendar by name only and not the strategy identity | `test_f4_*` (10 tests, 29 cases) | `OwnerSelections`: typed closed choices per decision, exact enum types, supported-set and contradiction checks, frozen; `M0Configuration` validates exact types, finite Decimals, ranges and cross-field constraints (`REFUSED_INVALID_CONFIGURATION`); a fixture may carry no selections; the data kind must be an exact `DataKind` (`REFUSED_MALFORMED_DATA_KIND`); a selected data window must cover the calendar (`REFUSED_SELECTION_INCONSISTENT`); `HISTORY_SESSIONS` is the accepted module's own 252 and no parameter; the trial record binds the strategy identity (version, parameters hash, required history), the calendar **content**, every setting, the phases, the membership rule and the benchmark and resolution versions |
| **5 — incomparable periods and one benchmark series.** Strategy figures ran through the purge / tail while the benchmark stopped at the window's last session, the benchmark's first-session return was excluded, both ledgers read the optimistic benchmark series, and a zero level produced a zero return | `test_f5_*` | two labelled periods per window — **evaluation** (from the close before the first session to the last session's close, identical instants for strategy and benchmark) and **liquidation-inclusive** (through the purge / tail, the benchmark covering the same extension); each terminal policy reads its own benchmark series; `ratio_return` yields `None` for a missing or zero level, never a fallback zero |
| **6 — reconciliation by placeholder.** The reconciliation test contributed `shares × 0` for open-at-end positions, and the fixture had none | `test_f6_*` | a transaction journal on every ledger (`ENTRY`, `EXIT`, `CASH_IN_LIEU`, `INTEREST`); open-at-end trades carry their mark session, mark price and unrealized P&L and are charged no exit; the regression rebuilds cash, realized P&L, remaining basis, marked value, unrealized P&L, commissions and interest independently from the journal and the raw bars for every ledger, baseline and sensitivity, with two open-at-end positions held through missing bars (ZZMM, ZZNN) and a cash-in-lieu case |

**Fixture extension** (`tests/fixtures/m0_exploratory.py`): `ZZPP` (signals on the last evaluation sessions),
`ZZQQ` (exits in the purge / tail attributed to the originating window), `ZZRR` (a time exit and a new signal at
one open, then an ordinary later re-entry), `ZZMM` / `ZZNN` (open at the end through missing bars), and
`with_split` (a variant layer carrying one split). **Every figure is synthetic**; the counts in the regenerated
report changed accordingly, and none is a strategy result.

**The governance correction.** The slice §9 records was directed to keep this ADR's status unchanged although the
authorization that produced it also directed the merge of PR #111 — the event this ADR's own clause names as its
acceptance. That contradiction is resolved here as directed: the merge evidence was verified (commit
`bc16801e…`, its parents and its tree, and that it is an ancestor of the corrected head) and the acceptance event
is recorded in the paragraph following the status line, the status rows in `CLAUDE.md` and `README.md` are
synchronized, the audit registry names the merge, and the present-tense claims that the ADR was still proposed
are corrected where they were claims rather than history. **This status correction accepts the vocabulary and
isolation decision only**: it selects none of O-1…O-11, authorizes no real-data run, and does not imply acceptance
of PR #112, which stays OPEN and unmerged.

## 11. Review correction 2 of the synthetic M0 path (2026-09-16, within open PR #112)

Source inspection of `95be27e6b3b0947294bee95d532b4f3b4f5d592a` raised two findings. **Targeted regressions were written
first** (`tests/unit/test_m0_exploratory_correction_2.py`, 8 tests) and run against that head before any correction:
**8 failed there**; all 8 pass after it.

| finding on 95be27e6 | correction |
|---|---|
| **1 — the split-effective open read that session's close.** `_apply_splits()` priced the fractional entitlement with the ex-session's close and credited the cash at the open, before the day's exits and entries — so an opening decision could depend on a price not yet observed, and a cash-constrained candidate could spend proceeds not yet settled | at the open only the whole-share quantity, the stop and the last close are rescaled; the fraction is **recorded, not priced** (`SplitEvent.fraction`, `SettlementPolicy.PENDING`; a whole-number rescaling is `NONE_DUE`). At the **close**, before marks, every pending entitlement whose security has an observed close settles at it, without commission, once (`Timing.CLOSE` in the journal): `EX_SESSION_CLOSE` on the ex-session, `NEXT_OBSERVED_CLOSE` when the ex-session had no bar. A position that exited at that open still receives the entitlement: its already-appended trade is restated with the settlement, its realized P&L and R multiple include it, its opening facts are unchanged, and the settlement stays attributed to that trade and its window. An entitlement that meets no observed close by the block's end is `UNRESOLVED`: listed on the ledger (`unresolved_entitlements`), carried on the trade as `unresolved_entitlement_shares`, valued at **zero** — a prior price is never read as a current close. **The whole fractional-share treatment is an M0 engineering assumption pending an owner selection**, and the report says so. Regressions: changing only the ex-session's close changes no opening fill, quantity or skip and only the settlement; a cash-constrained candidate is still `SKIPPED_CASH` at the open although the settlement at the close would have covered the shortfall; a position exiting at the split open receives its entitlement at that close, once, in its own record; the missing-close and never-observed cases are explicit and deterministic; cash, fractional assets, cost basis, realized and unrealized P&L and equity reconcile independently for every ledger, baseline and sensitivity, including open-at-end and unresolved cases |
| **2 — O-7 misassigned.** `OwnerSelections` carried a sizing choice at O-7 and a final-fill choice at O-10; the owner decision form defines **O-7 = events** (event-blind or wait for an event entity) and **O-10 = sizing and sequencing** (the CLAUDE.md §6 research parameters with one-pass sizing, final-fill rejection preserving both limits, and the ranking) | `o7_event_handling: EventHandlingChoice {EVENT_BLIND, WAIT_FOR_EVENT_ENTITY}` — only `EVENT_BLIND` is executable (it is D2; no event entity exists), `WAIT_FOR_EVENT_ENTITY` is `REFUSED_UNSUPPORTED_SELECTION`; `o10_sizing_and_sequencing: SizingSequencingChoice {CLAUDE_S6_FINAL_FILL_REJECTION, CLAUDE_S6_ONE_RESIZING_ITERATION}` — only rejection is executable. The former names (`SizingPolicyChoice`, `FinalFillPolicyChoice`, `o7_sizing_policy`, `o10_final_fill_policy`) are removed, so the substitution is **rejected** by the signature and never reinterpreted. The serialized record keys `O-7` / `O-10` carry the corrected values and are bound into the trial record and digest through the configuration document; the synthetic fixture still carries no selections at all |

**No owner decision is selected by this correction**; none of O-1…O-11 is taken, no real-data run is authorized, and
PR #112 stays OPEN and unmerged.

## 12. Slice 3 — the exploratory adapter (2026-09-16, a later and separately authorized slice)

**An implementation event; no decision and no execution.** Under an authorization limited to repository
implementation and synthetic tests, `kalpamani.data.exploratory.adapter` was written to turn an **admitted production
build's published bytes** into the objects the M0 runner reads, so that a future real-data run has one bounded, refusable
input path instead of a hand-built one. It reads bytes only — it has no store client, no read path and no principal — and
it emits an `ExploratoryPublication` through the existing `publish`, **never** an A1 `VerifiedPublication`.

| function | what it binds, and what it refuses |
|---|---|
| `parse_manifest(bytes)` | the accepted `kalpamani-production-build-manifest/v1`, parsed totally (closed key set at every level, exact types, duplicate keys refused, one contract version); yields the build's `as_of`, calendar version, configuration digest, commit, accepted-schemas version, observed schema digests, identity counts, pagination summary, the `served` counts (admitted / superseded / **excluded by time**), the `resolution_map` rule counts, the universe rule, the outputs (name → key, digest, bytes, rows, disposition) and the build input's runs with their payload digests |
| `parse_silver_artifact(name, bytes, expected_sha256, expected_bytes)` | one of `silver-tickers` / `silver-stocks` / `silver-actions` only (`NOT_A_SILVER_ARTIFACT` otherwise — **Gold is refused by name**); byte count and SHA-256 verified **before** parsing; every row document closed; each row back into the accepted `RowVersion` with its provenance; a redelivery gap's run ids are counted, their instants **never invented** (the artifact does not carry them) |
| `assemble_layer(manifest, artifacts)` | every dataset present and listed under `outputs` with a confirmed disposition; row count as listed; every row's provenance bound to a run and a payload digest the manifest's build input names (`PROVENANCE_UNBOUND`); **`REVISIONS_EXCLUDED_BY_TIME`** if any `served` count says the build could not serve a revision at its `as_of` — rows the research layer would silently lack are a refusal, not an omission |
| `calendar_from_configuration(bytes, manifest)` | the compiled build configuration whose **canonical digest equals the manifest's `configuration_digest`** (`CONFIGURATION_UNBOUND` otherwise) and whose calendar version equals the manifest's; the sessions carry `open_at` only — **the exploratory close is `open_at + 6h30`, an approximation stated in the module, not an exchange schedule, and early closes are not represented** |
| `rule_from_manifest(manifest)` | the accepted `UniverseRule` the build decided under; **`history_sessions` must be 252** (`RULE_HISTORY_NOT_ACCEPTED`) — the accepted module's own requirement, end to end |
| `build_dataset(assembly, calendar, rule, as_of=None)` | `resolve_as_dated` → the accepted membership clauses → benchmark A; `as_of` defaults to the build's and may not precede it; the dataset's `source_manifest_digest` is the manifest's SHA-256 |
| `publish_from_build(dataset, publication_id, limitations)` | the existing `publish`: an `ExploratoryPublication`, `LICENSED_DERIVED`, provenance naming the manifest |

**Proven on synthetic artifacts produced by the accepted producer** (`tests/fixtures/m0_build_artifacts.py`: the M0 synthetic
layer, re-keyed the production way, pushed through `availability.resolve`, `universe.build_universe`, `gold.build_gold` and
`build_manifest.build_manifest_document`; and the existing end-to-end build scenario's own published objects) by the ten
acceptance cases of the readiness packet (`tests/unit/test_exploratory_adapter.py`): (1) the adapted build and the direct
path yield identical layer, membership and benchmark digests and identical M0 trades under one trial digest; (2) a flipped byte
or a wrong byte count is refused before parsing; (3) the manifest is parsed totally; (4) a missing or unlisted artifact, an
unconfirmed disposition, an excluded revision or an unbound provenance is refused; (5) the calendar is the build's own or is
refused, and its close is the stated approximation; (6) a rule without 252 history sessions is refused; (7) provenance round-trips
exactly and gap instants are never invented; (8) the adapter imports only accepted contract modules, its output is exploratory
and every production consumer still refuses it; (9) Gold is not consumed and is refused by name; (10) the adapter takes bytes only
(no store, file or SDK call, checked structurally) and the real build scenario's objects round-trip, its 3-session rule refused.

**What the slice does not do.** It reads no licensed object — no principal, profile or path for that exists, and O-6 decides
where such a read would run; it runs nothing on real data (`run_m0` still refuses a `REAL` kind without a typed, complete
`OWNER_SELECTED` configuration); it selects none of O-1…O-11 or F-4…F-8 and does not select the fractional-settlement policy;
it changes no production module, P-2/P-3 rule, accepted threshold or build output. One correction to the readiness packet's
trace is recorded here: the excluded-by-time count the adapter must refuse lives in the manifest's **`served`** entries, not in
`resolution_map` (which carries the P-2 / P-3 / gated-evidence counts).

## 13. Slice 3, review correction 1 — the adapter's two boundaries (2026-09-16, a later and separately authorized correction)

**A correction event; no decision and no execution.** Independent review of the slice 3 head
(`9fb52b5e47c2ec6e0826ea3b4161772e752c20ce`) found two boundaries the adapter left open, both reproduced by
tests against that unchanged head before anything was corrected (`tests/unit/test_exploratory_adapter_correction_1.py`).

**Finding 1 — the configuration binding did not survive to dataset construction.** `calendar_from_configuration`
verified the compiled configuration's canonical digest against the manifest, and then `build_dataset` accepted **any**
calendar and **any** rule a caller supplied, checking only `calendar.version == manifest.calendar_version` and
`rule.history_sessions == 252`. A calendar with the right version and other sessions or opens, or a rule with 252
sessions and another price floor, ADDV floor, window or decision margin, was read as the build's. The correction:
`bind_configuration(document, manifest=…)` is now the **only** way a calendar or rule enters the module. It checks the
digest **first** (`CONFIGURATION_UNBOUND` before any field is read), parses the configuration document totally (the
closed shape `BuildConfiguration.document()` writes), derives the calendar and rule from those bytes, and **reconciles
every fact the producer writes twice** — the rule document, the calendar version, `as_of`, the commit, the
accepted-schemas version, the source-schema and transformation versions, and the observed schema digests (which must
be a subset of the accepted set) — with the **digest-bound configuration as the authority**: a manifest that repeats one
differently is `CONFIGURATION_INCONSISTENT` (the calendar version keeps its own `CALENDAR_VERSION_MISMATCH`). It
returns a `BoundConfiguration` carrying the exact bytes, the digest and the derived objects. `build_dataset(assembly,
configuration=…, as_of=None)` takes **only** that: it requires the configuration's digest to equal the assembly's
manifest's, **re-derives** the calendar and rule from the carried bytes and refuses if the carried objects differ
(`CONFIGURATION_INCONSISTENT`) — so a substituted calendar or an edited rule is refused whatever its version or history
count says — and applies the 252-session requirement to the build's own rule (`RULE_HISTORY_NOT_ACCEPTED`). The research
`as_of` override is preserved as a research parameter, distinct from build metadata: a later instant is allowed, an
earlier or naive one is `AS_OF_BEFORE_BUILD`. `calendar_from_configuration` and `rule_from_manifest` remain for
inspection (the first is `bind_configuration(...).calendar`); neither reaches dataset construction, and no parallel
unchecked path exists.

**Finding 2 — manifest validation stopped at the top level.** `parse_manifest` closed the top-level key set and the few
nested blocks it read (`identity`, `served`, `resolution_map`, `outputs`, `build_input.runs`) with a single
`MANIFEST_FIELD_MALFORMED`, and left the rest unread: `build_input` and `source_versions` were open mappings,
`transformation` was read by `.get()`, `completed_at`, `census`, `undecidable_sessions`, `quality`, `limitations`,
`spinoff_excluded_securities`, `restrictions`, `unresolved_contracts` and `empty_reason` were not validated at all,
`entries` was never compared to the digest lists, and no fixed value — classification, profile, policy, version, mode,
token, disposition — was held to the contract. The correction derives the exact schema from the accepted producer
(`build_manifest_document` and the component contracts it composes) and validates **every** field: closed keys at
every depth with one vocabulary (`MANIFEST_KEY_UNKNOWN` for an extra key, `MANIFEST_MALFORMED` for a missing key or a
non-object, `MANIFEST_FIELD_MALFORMED` for a wrong type or grammar — hex-64 digests, the 40-hex commit, the build-id
grammar, aware instants, ISO dates, non-negative counts, booleans, `str | None`); `entries == len(payload_digests) ==
len(record_digests)`; unique run ids, artifact names, artifact keys and census sessions; `checks_run` and
`checks_not_run` disjoint and duplicate-free; and every fixed contract value held to the accepted vocabulary as the new
`MANIFEST_VALUE_UNSUPPORTED` — the schema version, `LICENSED`, `PROVIDER_REALISTIC_PIT`, the source-schema, silver,
adjustment, action-selection, resolution, pagination and quality-plan versions, `SPLIT_ONLY` /
`FORWARD_BASE_NORMALIZED`, the acquisition modes, the limitation tokens, the restriction scope and the two confirmed
dispositions (`WRITTEN`, `ALREADY_PRESENT` — ADR-0040). The pagination record's fixed statements are taken from the
accepted `PaginationSummary.document()` itself. Genuinely dynamic maps — pagination group labels, quality check names,
finding scopes and severities, restricted and spinoff-excluded security identifiers, the evidence version — are validated
in type and shape (non-empty text, non-negative counts), not in membership. Values the adapter cannot import without
reaching a runtime module (the source-schema version, the quality-plan version, the adjustment policy, convention and
derivation version, the dispositions) are pinned and held equal to the producer's by a unit test.

**Regressions and validation.** 78 targeted tests [the count is corrected by the correction 2 note at the end of
this section: the run against the unchanged head was of a 69-test draft of the file]: against the unchanged head, 58
failed, 7 errored (no `bind_configuration`) and 4 passed (defects the head already refused: a negative served count, a non-integer pagination
count, a non-integer row count, a duplicated artifact); on the corrected tree all pass, together with the eleven
acceptance cases (case 4 now expects the unconfirmed disposition refused at parse; cases 5 and 6 exercise the
substituted calendar and rule through `BoundConfiguration`; case 10 binds the real scenario's 3-session rule faithfully
and refuses it at construction), the isolation and architecture guards, and the full suite. One fixture change: the M0
layer as an admitted build would carry it now bears the accepted pagination policy version instead of the fixture's own
`"synthetic"` label, which the producer never writes.

**Limitations, stated.** The adapter validates manifest **shape and vocabulary**; it does not recompute `run_id`
(`derive_run_id` needs the build inputs it cannot have), the ledger digest, the census or quality arithmetic, or the
Gold artifacts' digests (it does not read Gold). A producer that changes a fixed value has changed the contract, and the
adapter refuses until it is reviewed against the new value. Nothing else moved: no licensed object is read, no owner
decision is selected, no real-data run occurs, and P-2/P-3, the accepted thresholds and the 252-session requirement are
unchanged.

### 13.1 Review correction 2 — the evidence version, and the correction 1 accounting (2026-09-16, within open PR #113)

**A correction event; no decision and no execution.** Independent review of the correction 1 head
(`47b70d531fd548edeee02708dc4b2b46bffdb577`) found one repeated fact that §13's reconciliation left out, and one
miscount in §13's own record. Both were reproduced before anything was corrected.

**The finding — the evidence version was validated and discarded, never reconciled.** The producer writes the
availability evidence's version twice: as `evidence.version` in the digested configuration document and as
`transformation.evidence_version` in the manifest (`resolved.evidence_version`, which `availability.resolve` takes
from the same `AvailabilityEvidence`). `bind_configuration` validated the configuration's `evidence` block and dropped
the version it returned; `parse_manifest` admitted the manifest's field as dynamic text (it is not a value the adapter
can pin — §13); and nothing compared the two. A manifest whose `transformation.evidence_version` disagreed with the
digest-bound configuration was therefore bound, and `build_dataset` constructed a dataset under it — the one repeated
fact for which "the digest-bound configuration is the authority" did not hold. The regressions
(`tests/unit/test_exploratory_adapter_correction_2.py`, 12 tests) were run against the unchanged head first: **9 failed
and 3 passed** — **8 demonstrated acceptance defects** (four disagreeing versions, each bound by `bind_configuration`
and each built into a dataset by `build_dataset`: `DID NOT RAISE`), **1 missing-API failure** (`BoundConfiguration`
had no `evidence_version` attribute — an `AttributeError`, not an acceptance demonstration), and 3 controls the head
already satisfied (the fixture's two documents agree; a configuration-side edit is `CONFIGURATION_UNBOUND` because the
digest is checked first; the valid round trip). The correction: `bind_configuration` keeps the validated
`evidence.version` and reconciles it with `manifest.transformation_versions["evidence_version"]` — a disagreement is
`CONFIGURATION_INCONSISTENT`, in the same clause family as every other repeated fact; `BoundConfiguration` carries the
reconciled `evidence_version` beside the other reconciled facts; and `build_dataset`'s re-derivation compares it, so a
configuration bound to a consistent manifest and offered against an assembly whose manifest repeats the version
differently, or a carried value the bytes do not derive, is `CONFIGURATION_INCONSISTENT` at construction. Only the
manifest side can reach that comparison: editing the configuration document's own `evidence.version` changes its
canonical digest and is refused as `CONFIGURATION_UNBOUND` before any field is read. On the corrected tree the 12
regressions, the 78 correction 1 regressions and the eleven acceptance cases pass, with the isolation, architecture and
governance guards and the full suite. Nothing else moved: no defect member was added, no signature changed, the
producer's contracts are untouched, and no manifest value became pinned.

**The accounting correction.** §13 and the correction 1 record stated that 78 targeted tests were run against the
unchanged head `9fb52b5e` with 58 failing, 7 erroring and 4 passing. **The counts are right and the total is not**: the
preserved log of that run lists **69** tests (58 failed, 7 errored, 4 passed). The committed file has 78: after the head
run, ten tests were added (nine nested-manifest cases — `adjustment_derivation_version`, `silver_normalization_version`,
`pagination policy_version`, `quality plan_version`, `restriction scope`, `pagination fixed statement altered`,
`quality checks overlap`, `census duplicate session`, `outputs duplicated key` — and
`test_the_pinned_fixed_values_are_the_producers`) and one was removed (the manifest-disagreement parametrization ran
as eight unnamed `<lambda>` cases on the head and is committed as seven named cases; which of the eight was dropped is
not recoverable from the log, and is not guessed). Those eleven were never run against `9fb52b5e`; every count above is
of the 69 that were. The 69 also mix outcomes that §13 did not separate. Classified by re-running the committed file
against `9fb52b5e` (the correction 2 evidence; the eight `<lambda>` cases are classified through their seven committed
successors, which fail the same way): **42 demonstrated acceptance defects** — nested-manifest cases where
`parse_manifest` did not raise; **4 passes** — defects the head already refused; **5 cases the head refused under a
different member** than the corrected vocabulary names — four under `MANIFEST_FIELD_MALFORMED` where
`MANIFEST_KEY_UNKNOWN` / `MANIFEST_MALFORMED` is now distinguished, and the unsupported-classification case under a
member other than the then-absent `MANIFEST_VALUE_UNSUPPORTED`; and **18 missing-API errors and failures**, which
demonstrate that an API was absent and not that a document was accepted — the 7 errors (the `bound` fixture:
`adapter.bind_configuration` did not exist), the eight `<lambda>` cases and the not-the-producer's-shape case (the same
absent function), the signature test (`calendar=` / `rule=` still present), and
`test_r2_valid_producer_manifests_remain_accepted` (`BuildManifestView.completed_at` absent). The original log is
preserved unaltered; the correction 2 evidence carries this classification beside it.
