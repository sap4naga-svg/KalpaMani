# Phase 3A — A1 point-in-time foundation kernel

## STATUS: **IN REVIEW — NOT ACCEPTED, NOT COMPLETE**

| | |
|---|---|
| **Phase 3A A1 foundation implementation** | **IN REVIEW** |
| **Phase 3 overall** | **NOT COMPLETE** |
| [ADR-0005](../decisions/ADR-0005-point-in-time-data-architecture.md) | **PROPOSED** |
| Provider purchase / trial / credentials | **NOT AUTHORIZED** |
| External data acquisition | **NOT STARTED** |
| Short research | **NOT AUTHORIZED** |
| Phase 3B / 3C / 3D | **NOT AUTHORIZED** |

This document records what the A1 slice built, and — more usefully — what it did not. The
boundary in §2–§3 was written *before* the code, so it is a commitment rather than a description
of whatever got written.

> **Revision 3 (2026-08-26).** A second review closed the remaining *enforcement* gaps: the
> corrections in revision 2 were right, but several could still be walked around. Gold could be
> assembled from arbitrary rows; `BOUND` could be applied without checking that the bound actually
> resolved; a reader with no issue list was a clean reader; publication identity did not cover
> coverage, profile or policy evidence; Bronze filed content under the acquisition date; lineage
> replay ignored the dataset version; a zero-row universe snapshot vanished on write; minute
> coverage passed on one arbitrary bar; the manifest trusted caller-supplied input lists; and the
> survivorship alarm counted announcements as delistings. Section 13 lists each. No architecture
> changed and no scope widened.
>
> **Revision 2 (2026-08-26).** Independent review of the implementation found ten concrete
> defects. All are corrected; §13 lists each with the change. The substantive ones: an empty
> `FORWARD_SYSTEM` universe was **published** where it should have been **refused**;
> `ProfileResolutionConfig` was audit-only configuration that never touched the rows; a price
> query could mix resolutions and silently truncate a partially covered range; universe lineage
> attached every admissible input to every row; dataset publication was not atomic; limitation
> tokens were emitted from configuration rather than evidence; and one test assertion was
> disabled by an unconditional `or True`. No architecture changed — the kernel direction was
> accepted — and no scope widened.

---

## 1. What A1 is

A **vendor-neutral kernel**. It implements the merged Phase-3 planning contract
([pit-data-contract.md](pit-data-contract.md), [conceptual-schema.md](conceptual-schema.md),
[data-quality-plan.md](data-quality-plan.md),
[reproducibility-and-provenance.md](reproducibility-and-provenance.md)) as executable,
type-checked Python, and proves it against **deterministic synthetic fixtures owned by this
repository**.

> **It is a proof that the contract can be *mechanised*. It is not a proof that any vendor
> satisfies it, and it is not a claim about any real security, price or corporate action.**

The nine provider tests P1–P9 in [implementation-plan.md](implementation-plan.md) §2 remain
**unrun**, and cannot be run without a provider that has not been selected.

## 2. Authorized scope, and what was built

| Deliverable | Where |
|---|---|
| closed vocabularies | `data/contracts/vocabulary.py` |
| the two mutually exclusive envelopes | `data/contracts/envelope.py` |
| resolved availability times, origin eligibility, `source_anchor` | `data/contracts/resolution.py` |
| resolved fact-time anchors and the contract's domain-alias table | `data/contracts/anchors.py` |
| per-dataset gap resolution and the global downgrade | `data/contracts/profiles.py` |
| the resolution **execution** boundary and its receipt | `data/curate/resolution_run.py` |
| the sanctioned Gold build boundary | `data/curate/build.py` |
| the quality report -- publication and read gate | `data/quality/report.py` |
| safe path components | `data/contracts/paths.py` |
| exact per-security lineage selectors and their replay | `data/curate/lineage.py` |
| atomic dataset publication and verified reads | `data/curate/publication.py` |
| the single instant normaliser | `data/contracts/instants.py` |
| the Phase-3A entity subset | `data/contracts/entities.py` |
| canonical serialisation and content hashing | `data/contracts/canonical.py`, `serde.py` |
| the reproducibility manifest and deterministic `run_id` | `data/contracts/manifest.py` |
| immutable content-addressed Bronze | `data/ingest/bronze.py` |
| Silver normalisation | `data/normalize/silver.py` |
| local analytical storage | `data/storage.py` |
| adjustment proof and historical-universe proof | `data/curate/` |
| deterministic quality checks | `data/quality/checks.py` |
| point-in-time accessors | `data/pit/accessors.py` |
| synthetic reference dataset | `tests/fixtures/phase3a.py` |

Roughly 10,400 lines of source and 7,400 lines of tests and fixtures.

## 3. Explicitly NOT authorized, and not done

> any paid or free vendor trial · vendor account creation · provider purchase or subscription ·
> requesting, entering or storing a provider credential · calling a real vendor API ·
> downloading external market data · importing real vendor payloads · scraping provider sites ·
> SEC / EDGAR ingestion · QuantConnect dataset download · IBKR market-data or borrow-data
> qualification · connecting to IBKR · deploying LEAN · submitting or cancelling an order ·
> strategy, scanner, ranking, portfolio or risk implementation · analyst estimates or revisions ·
> historical borrow implementation · short backtests · Phase 3B, 3C or 3D · accepting ADR-0005 ·
> resolving G1–G5 · merging the implementation pull request

**No synthetic result in this slice is vendor qualification or production evidence.**

## 4. Dependencies added: **NONE**

`pyproject.toml` still declares `dependencies = []`, and a test asserts it.

**The merged plan recommends Parquet + DuckDB, and that recommendation stands** for the layer
that will hold real vendor history. It was not adopted here, for three reasons:

1. **This slice must prove determinism and content-addressed identity, not analytical
   throughput.** It holds a few dozen fictitious rows. Newline-delimited canonical JSON gives
   both properties with the standard library alone.
2. **Choosing a data engine before gate G1 fixes it ahead of the decision that determines the
   volume it has to serve.** G1 selects the provider; the provider determines the data size and
   shape; the engine should follow, not lead.
3. **A zero-dependency kernel is installable and testable with nothing but Python.** That is
   worth keeping while the repository is public and no provider exists.

The on-disk layout is the one [implementation-plan.md](implementation-plan.md) §1.3 specifies, so
adopting Parquet later is a **writer change, not a rewrite**. PyArrow was not added either, by
the same reasoning and because nothing here needs it.

## 5. Local storage layout

```
<root>/bronze/objects/sha256/<sha256>.json.gz                  content, by digest alone
<root>/bronze/acquisitions/<provider>/<dataset>/<date>/
        <sha256>.<run_id>.json                                one record per retrieval
<root>/silver/<dataset_version>/<entity>.jsonl
<root>/gold/<dataset_version>/<entity>.jsonl
<root>/gold/<dataset_version>/_dataset_manifest.json
<root>/gold/<dataset_version>/_quality_report.json
<root>/gold/<parent>/_staging-<leaf>/…            uncommitted; invisible to readers
```

**Bronze content is globally content-addressed.** The same bytes fetched on two dates, or under
two runs, are **one** object. Filing content under the acquisition date would store the payload
twice and make a re-fetch look like new data. Each retrieval writes its own acquisition record;
a second legitimate acquisition is not a repair, and only completing an *interrupted* acquisition
identity reports one. Re-writing an acquisition identity with different metadata is refused --
one retrieval happened once.

**Every identifier reaching the filesystem is validated first.** Provider, dataset, entity,
ingestion-run id and each segment of a dataset version pass through `safe_component`. Refused
rather than sanitised: rewriting a bad name would map two identifiers onto one path, and two
datasets sharing a directory is a corruption that verifies.

**Publication is atomic.** A version is assembled in a staging directory — every table written
and `fsync`-ed, then the dataset manifest — and committed by a **single directory rename**. The
rename *is* the commit: before it nothing is visible under the published name, after it
everything is. A reader never sees a manifest describing tables that have not landed, nor tables
no manifest describes. Versions are superseded, never rewritten.

**Reads verify before they decode.** Build time, coverage, resolved profile, the complete
resolution map and the quality evidence all come from the persisted manifest, never from
arguments. Every table hash is checked before its rows are parsed, the decoded row count is
checked against the declared one, and the manifest body is checked against `manifest_hash` --
which covers everything except itself. Two manifests differing in coverage, profile or policy
evidence therefore cannot share a dataset identity.

**Bronze separates two immutable things.** A *content object* keyed by payload digest alone, and
an *acquisition record* per retrieval keyed by `(digest, ingestion_run_id)`. Fetching the same
bytes twice records two acquisitions over one payload — the honest account. They are written
content-first, acquisition-second, so the only reachable inconsistency is a payload with a
missing acquisition record, which a retry **repairs**. The reverse order would leave an
acquisition naming a payload that does not exist, which nothing on disk could repair. A write
never reports success while the metadata is absent.

The root is **always an explicit argument**. The default configured path
(`DEFAULT_DATA_ROOT = .runtime/data`) is a path *value*: importing the package creates no
directory and performs no I/O, and a test asserts it. All tests write to temporary directories.

**The Bronze hashing contract, stated once and tested:** identity is the SHA-256 of the
**uncompressed payload bytes**. Gzip is a storage encoding, not part of identity. Compression
uses a fixed zero `mtime` and a fixed level, so two writes of the same payload produce
byte-identical files. Acquisition metadata lives in a sidecar, because mixing it into the payload
would make identity a property of when we asked rather than of what the vendor sent.

## 6. Profile behaviour

- `PUBLIC_PIT` serves `AUTHORITATIVE_PUBLIC` rows on `resolved_public_time`.
- `PROVIDER_REALISTIC_PIT` requires **both** resolved axes for a public fact, and
  `resolved_provider_time` for a proprietary one.
- `FORWARD_SYSTEM` is governed by the max over the times a record actually has, including
  `system_first_seen_time`.
- A derived artifact's availability is the max over its lineage, plus `artifact_first_built_time`
  under `FORWARD_SYSTEM` only; its **eligibility is the intersection** of its inputs'.
- `EXCLUDE` and `BOUND` are **per dataset**; `DOWNGRADE` is **global** and relabels the whole run
  `PUBLIC_PIT` before any filtering. There is no `DECLARE`, and a test asserts its absence.
- Nothing is approved by default: a dataset absent from the approved-bound configuration has
  **no** approved bound, so an unapproved bound cannot resolve an axis.

**Eligibility is kept separate from availability throughout.** An ineligible row is *excluded and
counted*; an eligible-but-unresolvable row is *refused*. They call for opposite responses, and
collapsing them is how a factor quietly loses an input.

### An unbuildable universe is refused, not published empty

`FORWARD_SYSTEM` **cannot build a 2019 universe from reference data first seen in 2026.** The
first implementation published the resulting empty snapshot; that was wrong. An empty snapshot
and an unavailable one look identical downstream and mean opposite things, and publishing one
would let a profile that cannot reach back before we existed answer a historical question with a
zero-security market.

The build now **refuses** with `REQUIRED_INPUT_UNAVAILABLE`, naming the emptied domains and the
cutoff. Three outcomes are kept distinct, and each has a test:

| situation | outcome |
|---|---|
| the rule ran and selected members | a valid snapshot with members |
| the rule ran on admissible inputs and selected **nobody** | a **valid** snapshot, every row a non-member with its exclusion reason |
| the required inputs were all inadmissible | **refused** — no snapshot exists |

`FORWARD_SYSTEM` still never substitutes `PUBLIC_PIT`. Refusing is what the contract means by
"mandatory for forward validation, never valid for long histories".

## 7. Quality checks implemented

Envelope conformance branches on envelope **before anything else** (§4.0A source / §4.0B
derived), then: unresolvable public timing · proprietary rows carrying public timing ·
system-observed rows carrying vendor timing · exact-derivation-without-exact-value ·
approximation written into an exact field · bound preceding the exact time it bounds · unapproved
bound · derivation disagreeing with origin · a declared class with no resolved anchor · incomplete
lineage · missing derived-envelope fields · output validity without its field.

Temporal: held-before-public · held-before-provider · written-before-first-seen ·
provider-ahead-of-public · the three class invariants against one origin-aware anchor ·
future-dated availability.

Market data: impossible OHLC · non-positive price or negative volume · duplicate bar key ·
session date derived by UTC truncation · bar outside any known session · split discontinuity with
no action explaining it · missing bars in a listed range · adjusted-cache hash mismatch.

Identity and universe: ticker overlap · survivorship leakage · delisted absence · rebuild drift ·
eligibility from inadmissible data · profile-free or mismatched membership.

Profile: mixed profiles · ineligible row served · unresolved provider availability · public timing
substituted for absent provider timing · `BOUND` on a system-observed row · backfill admitted too
early · dataset absent from the resolution map · resolution map or policy version absent from
`run_id` · downgrade not carried through.

Envelope-shape checks that the type system already makes unreachable are applied to **rows read
back from storage**, which is where a malformed envelope can genuinely arrive: an older writer, a
hand edit, a partial restore. They are executable, not prose.

All checks are deterministic and return typed findings. **No AI, no sampling, no probabilistic
judgement.**

**A versioned quality plan says what should have run, and a runner runs it.**
`phase3a.quality-plan.1` declares the expected check ids, which are REQUIRED and which may be
not-run, each check's dataset scope, the closed vocabulary of finding ids it may emit, and the
implementations that produce them. Publication and read both validate the report against it as a
**closed** comparison, so a report listing one harmless check and no findings -- which looks
exactly like a complete clean pass -- refuses.

`phase3a.quality-runner.1` then makes the report a product of that plan rather than an account of
it: it invokes every applicable implementation and builds the report itself, so `checks_run` comes
from invocation and `checks_not_run` only from an applicability decision the runner computed from
the build. Publication accepts no other report. Two checks are CONDITIONAL:
`7_cross_provider_reconciliation`, because reconciliation needs two independently licensed sources
and there are none, and `4.5_adjusted_artifacts`, because a build that materialised no adjusted
artifact has no cache to reproduce -- a decision the runner reaches from the build, not one a
caller can ask for.

## 8. Synthetic fixture coverage

Four fictitious securities, an invented calendar, invented prices, and no clock anywhere:

- a continuously listed common stock, and the split-adjustment proof built on it
- a ticker rename (`KTHN` → `KTHX`) where identity survives
- a security delisted 2019-06-28: **present** in the 2019-06-27 snapshot, **absent** afterwards
- a ticker (`OBSQ`) legitimately recycled by a different security in 2021 — which must **pass**;
  only an *overlap* is a defect, and that adversarial variant is tested separately
- a regular session, a **half-day** session, and two distinct **minute bars** in one session
- a **programmatically generated dense minute grid** over one regular session (390 endpoints) and
  one half day (210), derived from the venue calendar rather than listed, so the accepting path is
  proven end to end and the half day is short on purpose rather than short by omission
- a split announced 2019-06-25 with a 2019-06-27 ex-date — knowable on the 26th, applied only
  from the 27th, and invisible at an as-of of the 24th
- a date-only announcement resolved by an approved `DATE_PLUS_LAG` bound
- all four timing shapes: exact public, bounded public, exact provider, bounded provider
- one `PROVIDER_DERIVED` fact (ineligible under `PUBLIC_PIT`, excluded and counted)
- one `SYSTEM_OBSERVED` fact (eligible only under `FORWARD_SYSTEM`)
- listing **revisions 0 and 1**, so a delisting is a later revision available only once it
  happened, rather than a fact known from the listing date
- a derived adjusted-bar artifact, and historical universe snapshots either side of a delisting

**Negative controls carry as much weight as the adversarial cases.** A check that over-blocks is
not "safe"; it is a check somebody will switch off. Every negative control in the suite is
labelled as one.

## 9. Security posture

The repository is **PUBLIC** (CLAUDE.md §3) and
[INC-0002](../incidents/INC-0002-account-binding-digest-exposure.md) remains **OPEN**.

- Every fixture is **fictitious**. No vendor row is copied, quoted or paraphrased.
- No credential, account identifier, account-binding digest or broker order id appears anywhere
  in the data platform. Cross-cutting invariants 9 and 10 of
  [conceptual-schema.md](conceptual-schema.md) §19 are enforced by test, over the source, by AST
  and text scan.
- `.gitignore` now excludes `.runtime/data/`, `*.duckdb`, `*.duckdb.wal` and generated
  Parquet/JSONL under runtime paths **explicitly**, rather than by inheritance from `.runtime/`.
  Repository-owned synthetic fixtures under `tests/` are deliberately **not** matched: they must
  stay reviewable.
- No network client exists in this slice. No test opens a socket. `duckdb`, `pyarrow`, `pandas`,
  `boto3`, `requests`, `httpx` and `psycopg` are asserted **not importable**.
- The historical GitHub purge-request document remains untracked operational material and was
  not modified, committed or used as visibility governance.

## 10. Open decision gates — unchanged by this slice

| Gate | Subject | Status |
|---|---|---|
| G1 | Provider selection | **OPEN** |
| G2 | Production information-set profile | **OPEN** |
| G3 | Vendor licensing | **OPEN** |
| G4 | The analyst-estimate gap | **OPEN** |
| G5 | Borrow-history qualification | **OPEN** |

None is resolved here, and none may be resolved silently by an implementation choice. Where the
kernel needs a value a gate would settle — which profile governs production research, for
instance — it takes it as a **required argument with no default**, so the gate stays visible
instead of being answered by whichever call site ran first.

## 11. Acceptance limitations — what this slice does NOT establish

These are boundaries of a deliberately narrow slice, not defects:

1. **No vendor data has been read**, so no provider claim is qualified. P1–P9 are unrun.
2. **`SPLIT_AND_DIVIDEND` and `TOTAL_RETURN` are refused, not implemented.** The merged contract
   names the policies but does not fix a dividend convention. Inventing one would bake it into an
   artifact hash and have it cited later as though it had been decided. `SPLIT_ONLY` is complete.
3. **`get_classification` is contractually defined and refuses at runtime.**
   `classification_history` is outside the Phase-3A entity subset and no fixture carries it. It
   raises a named error so a caller can tell *not built yet* from *this security has no sector*.
4. **The universe market-cap threshold is unsatisfiable and refuses.** Shares outstanding is a
   Phase-3B fundamental. A definition declaring `min_market_cap` is rejected with
   `REQUIRED_INPUT_UNAVAILABLE` rather than computed without it.
5. **Universe thresholds are versioned synthetic parameters**, not Blueprint §4 production
   thresholds over real data.
6. **Phase-3B and 3C entities are not defined** — filings, fundamentals, earnings, estimates,
   transcripts, borrow. A schema with no data behind it is a promise this slice is not authorized
   to make.
7. **Parquet, DuckDB and object storage are deferred** (§4).
8. **Cross-provider reconciliation (§7 of the quality plan) is not implemented**, because it
   requires two licensed sources and there are none.
9. **`data.live` is empty by design.** The boundary exists before there is anything behind it, so
   it is inherited rather than retrofitted.
10. **The survivorship alarm needs deep history to say anything.** Over a dataset whose snapshots
    are all recent it draws no conclusion at all -- correctly, but that means it is not a check
    a short-horizon build gets any assurance from. It now also requires deep-history snapshots
    that actually **selected members**: two empty ones used to raise the alarm between them,
    which is a conclusion drawn from no evidence.
11. **Silver has no published-version machinery yet.** Only Gold is published atomically with a
    manifest; Silver remains a plain table layer, because nothing in A1 reads Silver back.
12. **The quality plan and runner are versioned by this code, not by the planning package.**
    `phase3a.quality-plan.1` names the checks, their scope, their finding vocabulary and the
    implementations that produce them; `phase3a.quality-runner.1` invokes them. Together they
    make the report a *product* of checking rather than an account of it. They do not make the
    check **content** Blueprint-complete: a plan naming the right checks, executed faithfully, is
    still not evidence that each check is thorough.
13. **`4.3_profile_service` runs over the rows the build would serve, not every stored row.**
    Gold deliberately stores rows the resolved profile cannot serve and filters them at query
    time, so handing the whole build to a check whose subject is "rows in a result" reports every
    one of them as an ineligible row served. What the check establishes at build time is that
    everything the build *would* serve resolves, is in the resolution map, is keyed to one
    profile, and was not admitted before it was knowable. Check 4.3.5 remains a query-path
    guarantee.
14. **The reference fixture carries two genuine warnings.** Both continuously listed securities
    are listed on the half-day session and have no bar for it. They are reported, not suppressed:
    a warning labels rather than blocks, and a fixture with nothing to report would not
    demonstrate that the runner reports anything.
15. **The atomic-selection fallback needs a dataset built incrementally to exercise.** Within one
    build every membership decision is admissible by its session's evaluation cutoff, so a
    snapshot that is a candidate is also complete. The fallback and the late-arriving-decision
    refusal are therefore tested against a dataset whose two snapshots were first built at
    different times -- which is what an incremental pipeline produces, and what this slice does
    not otherwise build.

## 12. Immutability closure applied in revision 8

Revision 7 bound a run to its dependencies and its evidence to a standard. This round makes the
standard itself unable to move: `frozen=True` refuses reassignment of an *attribute*, and says
nothing about the dictionary the attribute points at.

| # | Gap | Closure |
|---|---|---|
| 1 | `BoundApprovals` wrapped a caller-owned mapping | `source = {...}; approvals = BoundApprovals(by_dataset=source)`, hand it to a reader, then `source["price_bar"] = permissive` — nothing in that sequence touches the frozen object, and the reader had already compared these approvals against the publication's persisted standard and found them equal. From the next query onward it resolves rows under approvals nobody agreed to. An approved bound is what lets a row resolve at all, so this decides which rows a later query returns. The mapping is now copied and wrapped in a `MappingProxyType` in canonical key order at construction; the nested `ApprovedBoundPolicy` values are frozen dataclasses over `frozenset`s, so the value is immutable to its leaves and `identity()` is fixed for its lifetime |
| 2 | `QualityContext.evaluation_cutoffs` had the same shape | A caller could move the instant a snapshot was evaluated at **after** the descriptor was generated and the context hash taken — so the standard a build was judged against moved while every hash over it went on agreeing with itself. Copied, proxied and instant-normalised at construction. An AST sweep over every frozen dataclass in `src/kalpamani/data/` confirms these were the last two: `GoldDataset.universe`, `GoldDataset.universe_headers`, `InputInventory.dataset_manifest_hashes`, `ResearchManifest.definitions`, `ResolvedRunInputs.by_dataset`, `ExecutionEvidence.dataset_manifest_hashes` and `QualityReport.policy_versions` were already deep-frozen |
| 3 | The reader's standard identity was compared and discarded | One comparison at construction is now **sufficient**, and the reason is a property rather than a hope: the approvals value cannot change, so the value compared is the value every query uses. Re-deriving that comparison before each accessor call would be a check with no reachable failure — the "assertion dressed as a derivation" pattern the last two rounds kept finding. `PointInTimeReader.approvals_identity` keeps the canonical identity instead, so a test observes that it does not move rather than trusting that it cannot. `BoundApprovals.canonical()` is the one spelling, shared by the reader's comparison and the quality-context descriptor, so the two cannot drift into a disagreement that is really a formatting difference |
| 4 | The audit claimed more than it checks | Its success line read *"Every scanned assertion can fail"* — which a syntactic scan cannot establish, and revision 7's review proved by finding an `assert not P or P` it could not see. It now reports that no **syntactically** unconditional assertion, broad test exception or unexplained skip was found, and says in the same breath that this is not proof every assertion is semantically capable of failing. Its AST checks are unchanged, and a test asserts both the narrower wording and that all three detection classes still refuse |

`MANIFEST_VERSION` stays **5**: nothing about the persisted schema changed.

**One mutable mapping is left, deliberately.** `TradeRecord.orders` in
`src/kalpamani/execution/state_store.py` is a `dict[str, SubmittedOrder]` on a frozen dataclass —
the same shape. It is Phase-2 execution state, outside this slice's authority and outside the
quality-context and reader surface this round was scoped to, and changing it would touch certified
Phase-2 behaviour. Recorded here rather than fixed silently or left unmentioned.

### What adversarial review of revision 8 then found

Nine confirmed, all fixed. The first pass closed the *mappings* named in the review and left the
level below them open, which is the shape worth recording: a deep-freeze that stops one level
short is a shallow freeze with a longer docstring.

**The annotations do not enforce themselves.** `ApprovedBoundPolicy(public={x})` stored the
caller's mutable `set` inside a value the rest of the system treats as immutable — the same defect
as a frozen dataclass wrapping a caller's dict, one level down, and it made the outer freeze
pointless: a reader's construction-time agreement check passed and the approvals it went on serving
then gained a derivation the publication was never judged against. A `frozenset` **subclass** was
worse still, because overriding `__contains__` splits what the resolution reads from what
`canonical()` records, so the two come apart with no hash moving. A `str`-subclass key with an
unstable `__eq__` does the same to `for_dataset`. Every field is now rebuilt as a plain `frozenset`,
`tuple` or `str`. The same coercion was missing on `UniverseDefinition.eligible_exchanges`,
`ProfileResolutionConfig.dataset_resolutions` and `QualityContext.adjusted_artifacts` — all three
hashed into the persisted standard.

**Immutability is not inheritable.** `BoundApprovals`, `ApprovedBoundPolicy` and
`ProfileResolutionConfig` could each be subclassed, and the coercion and the accessors are both
overridable — so a subclass answers the reader's one agreement check and its per-query reads
differently. `ProfileResolutionConfig` matters most: `resolved_profile` is a property the reader
re-reads on every query. All three now refuse subclassing, and the reader checks the exact type of
everything it binds to, before dereferencing any of it.

**Two identities were blind to what they were supposed to pin.** `registry_identity` hashed
implementation ids and declared finding vocabularies, so a registry whose every `invoke` returned
nothing hashed identically to the real one. And a derived row's `inputs` — what
`decision_available_time` walks and what `6.6_eligibility_from_inadmissible_data` examines —
reached no identity at all, so dropping one changed what the checks looked at while the header's
hash, the build's and the descriptor's all stayed put. A related crash: `inputs` are in-memory
only, so every *decoded* header carries none, and `max()` over nothing raised a bare `ValueError`
from inside a check. Unresolvable is the honest answer, and the reader already gave it.

**And the audit still over-claimed in four more places** — its title line, its opening premise, two
class docstrings and a parametrised test named for "every" spelling — while the guard test pinned
one exact substring, which the same claim reworded would pass. The guard now rejects any success
line that speaks about failing without narrowing it to what a parser can see.

## 13. Dependency and provenance closure applied in revision 7

Revision 6 bound a result to the question that produced it. This round closes what a run
**depends on** — the inputs a query actually rests on, the artifact that decides a snapshot, and
the standard a build was judged by — and removes two assertions that could not fail.

| # | Gap | Closure |
|---|---|---|
| 1 | Two assertions were tautologies | `assert x in str(y) or True` reads as a check and is not one: `or True` makes the whole expression unconditional, so the interesting half was never evaluated. Both would have passed against a build with no binding at all. They are replaced by perturbation proofs — change one load-bearing row under an unchanged version label and the context hash moves; change `quality_context_hash` and `compute_manifest_hash` moves — and `scripts/test_integrity_audit.py` scans the parsed tree of the whole `tests/` directory for **syntactically** unconditional assertions, broad `pytest.raises(Exception)`/bare handlers inside tests, and unexplained skips. A test runs it, so the property stands rather than being cleaned up once. It is a guard over those syntactic properties and not proof that every assertion can fail — a distinction revision 8 makes the audit's own output say |
| 2 | `VerifiedPublication` was a copyable dataclass | Two compounding defects: `verified_by` sat in a readable field, so `dataclasses.replace` carried the token onto substituted rows for free, and `verification_seal` was **public**, so a caller who swapped the dataset could recompute the seal over the replacement and restore the agreement the seal existed to prove. A seal its holder can recompute is a checksum, not an authorization. It is now a non-dataclass with no authorization field, a module-private seal, and `require_internally_consistent()` re-deriving eight identities — which `PointInTimeReader` calls at construction rather than reading a flag: "it was verified once" and "it holds now" are different claims |
| 3 | A price query recorded only its bars | Completeness is measured against an endpoint grid, and the grid comes from the security's listing states and its venue's calendar. `market_session` was the one input never filtered point-in-time, so a calendar correction published in 2026 decided what a 2019 query expected. Both tables are now selected as-known-at-`as_of`, refused when contradictory at one revision, recorded in `direct_source_datasets` with their own timing evidence, and hashed into the query's `grid_basis_hash`. A window with trading sessions but no admissible calendar **refuses**, because an empty grid would report that the security traded on no session — a different finding, and a wrong one |
| 4 | Snapshot availability was computed by scanning rows | A security the rule considered and excluded produced no row, so it could delay nothing; a snapshot with no rows at all had an empty maximum and looked available from the beginning of time. The header is a real derived artifact carrying every considered listing and every membership decision, so `decision_available_time(header)` **is** the snapshot's decision time. Membership checks remain, as integrity checks: they do not turn one stored artifact into a partially available one |
| 5 | One function answered two different questions | `governing_timing_bases` returned the union of every axis a profile consulted. Under `PROVIDER_REALISTIC_PIT` an authoritative-public row needs both a public and a provider time and is available at the **later** of the two: both required, one governing. The union therefore reported an exact provider time as having set a cutoff a bounded public time set, and the reverse. `required_timing_bases` and `governing_timing_bases` are now separate and both mirror `decision_available_time` axis for axis; a derived artifact governs through its **slowest** input, and `ARTIFACT_FIRST_BUILT` governs under `FORWARD_SYSTEM` when it is the maximum. The bound-required tokens rest on the required set |
| 6 | The standard was hashed and not recorded | A hash proves two contexts differ and tells an auditor nothing about either: a published dataset carried sixty-four hex characters where a minimum price, an approved bound derivation and a survivorship window should have been readable. `QualityContextDescriptor` records all of them — plus the resolution map with its reasons, the cutoffs, the runner, the plan and the registry — inside the quality report. Its canonical form enters `report_hash`, the persisted file hash and the dataset manifest, and the read decodes it, recomputes `quality_context_hash` and refuses a mismatch |
| 7 | Coverage was one bit for three situations | A table traversed and full, a table traversed and empty, and a table nothing opened are three different statements, and only the first two are coverage. `TableCoverage` records which, per published entity, with the governed reason where nothing ran. The adjusted-artifact check compared a series to **its own** stored hash — which detects an edited file and nothing else — and reported the entity covered on that basis; it now runs the full `verify_adjusted_bar_artifact`: lineage resolved to the exact rows in the builds it names, the key rebuilt, the series recomputed from only those rows. `partitions_covered` are partitions an implementation actually traversed, not every configured cutoff |
| 8 | The manifest restated what the run had established | Both profiles, the window, the cutoff, the revision view, the finding counts and the dataset identity were written beside evidence that already fixed them, with nothing comparing the two halves — and each half reads correctly on its own. Every one is now held to the sealed result. `emit_manifest` takes the bytes the run sealed rather than asking for them again, and the `QuerySpec` is validated against the typed result and its provenance at seal time |
| 9 | A revision tie was broken by input order | `max` returns whichever tied row it saw first, so the order rows happened to arrive in decided which ratio, ex-date or listing status was in force. Two **different** rows at one revision sequence now refuse; identical duplicates are one row and pass. Adjusted queries reuse `relevant_actions` rather than restating its rules, so the on-demand and materialised paths cannot drift about the convention again |

`MANIFEST_VERSION` stays **5**: this round changed what a run records about its dependencies, not
the schema it records them in.

**What the point-in-time calendar filter immediately found.** The synthetic calendar's provider
axis is a `FIRST_SEEN_UPPER_BOUND`, and the resolution step derives that bound from when the row
was first held — 2026. Under `PROVIDER_REALISTIC_PIT` the calendar was therefore never available
to a 2019 query, and every provider-realistic price query in the fixture had been measuring
completeness against sessions it could not have seen. That is the fixture's own declared BOUND
policy working correctly; the tests that relied on it now either ask after the calendar was
available or assert the refusal.

**And what the new seal-time check found.** `_validate_revision_view` returns a view for the
adjustment path to use, and a RAW series was reporting that value in its **provenance** — telling
a caller the answer had honoured a view it never read. The query spec had been corrected in
revision 6; the caller-visible result had not.

### What adversarial review of revision 7 then found

Each closure above was handed to an independent reviewer instructed to break it, and every
reported hole to a second reviewer instructed to refute it. Thirty-four candidates were reported
and **twenty-five confirmed real**. All are fixed; none is outstanding. Four groups, and the
pattern is the one every round has had -- a check that measures a claim against something
*adjacent* to it.

**A guard that could not see its own subject.** The very file this round cleaned still contained
``assert not any("BOUNDED" in basis for basis in used) or bounded`` -- two spellings of one
predicate, `not P or P`, unfailable for any dataset and invisible to a syntactic scanner. The
audit now folds literal comparisons and containers, sees ``from pytest import raises``, and states
in its own docstring what it cannot do: passing it means no assertion is unconditional **by
construction**, not that every assertion can fail. Two more tests were compared to derivations of
themselves -- ``bounds_relied_upon`` against the tuple it is derived from, and "the two adjustment
paths agree" against a substring of the reader's source -- and both now compare values a revert
would move. One test's stated premise was the opposite of what the fixture produces.

**Assertions dressed as derivations.** ``_bound_is_approved`` was replaced in this round with
arithmetic that returned ``True`` for every row that has ever existed: a bounded basis only arises
because the derivation was *already* found in the approved set, so the guard tested a condition its
own precondition had excluded. The reachable question -- and the useful one -- is about a row the
query could **not** admit. ``run_id_inputs`` read the resolution map off the config and handed the
same config to the check, so both comparisons compared a value to itself; it now reads the build's
own receipt. ``QualityContext.as_of`` was documented as "the build's own time" and compared to
nothing, so a caller could move the horizon that ``4.3.9_backfill_admitted_too_early`` measures
against.

**Half a dependency is not a dependency.** The adjusted price path never had ``listing`` or
``market_session`` added to its dataset tuple, so only raw queries recorded the grid's inputs. The
calendar refusal fired only when the *whole* calendar was invisible, leaving the worse half open: a
partial calendar silently shrank the grid to fit what was visible. The artifact key rebuild took
scope and interval straight off the artifact -- the two fields the key most exists to protect were
the two it could not check. And the materialised adjustment path never collapsed revisions, so a
restated split entered its artifact **twice**; the reader had fixed that, which is exactly how it
stayed invisible.

**A standard nobody applied.** The descriptor's resolution fields were copied from a
caller-supplied config that nothing reconciled with the build. ``DatasetReference.content_hash``
and ``layer`` were compared to nothing and entered ``run_id`` -- every green test in the repository
emitted a manifest whose dataset content hash was the literal ``"sha256:abc"``. And the reader took
its ``BoundApprovals`` from a parameter while the publication recorded the ones the build was judged
under: the standard was persisted and verified, and the one component that applies a standard at
query time ignored it.

## 14. Query identity and quality-context closure applied in revision 6

Revision 5 made a result whole and made the checks actually run. This round closes the places
where evidence was still a **claim nobody produced**: a query the manifest described but nothing
executed, a coverage list the plan declared rather than the checks earned, and a standard the
build was judged by that nothing recorded.

| # | Gap | Closure |
|---|---|---|
| 1 | `PointInTimeReader.seal(result, result_bytes)` sealed anything a caller handed it | The seal existed to say "an accessor produced this under a recorded execution", and a public method stamped it onto objects the accessor had never seen. It is gone, along with the reader-lifetime `execution_evidence()`: each accessor creates a **fresh `ExecutionRecorder` per call** and returns its own sealed `ExecutedResult`. Accumulating across a reader meant a universe query's manifest truthfully claimed to have read price bars, because an earlier query had |
| 2 | The seal was a token in a readable dataclass field | `dataclasses.replace(sealed, result=anything)` copies every field it is not asked to change -- the token included -- so a genuine seal landed on substituted contents and every check it guarded passed. `ExecutedResult` and `RunnerOutcome` are no longer dataclasses, refuse construction without a module-private token, and refuse attribute assignment outright. `replace` cannot reach either; the consuming operation revalidates the identities rather than trusting the wrapper |
| 3 | `run_id` rested on a caller-authored narrative | `backtest_start`, `backtest_end`, `definitions` and `revision_view` are prose: they can say anything, and nothing compared them to what ran. A typed `QuerySpec` -- `PriceQuerySpec` or `UniverseQuerySpec` -- is now **generated by the execution**, travels `ExecutedResult` -> `InputInventory` -> `ResearchManifest` -> `run_id`, and the narrative fields are held to it: a window, a cutoff or a view that contradicts the query refuses. A RAW series consulted no revision, so its spec records **none**; the validator's internal return value was being written into the manifest, reporting a view the query never read |
| 4 | Limitation tokens came from dataset-wide timing evidence | A build containing bounded rows and a result that leant on one are different claims. Timing basis is now recorded **per served row** -- exact or bounded, public or provider, system-first-seen -- and `bounds_relied_upon` names the datasets whose rows *this answer* actually used a bound for. A run serving only exact times no longer carries `PROVIDER_TIME_BOUNDED`. Two different `ConsumedArtifactRecord` values under one `artifact_id` are refused rather than last-write-wins |
| 5 | `OPTIONAL` could be read as permission to stop checking | It relaxes **availability, and only availability**. Primary-key uniqueness, on-grid placement, no off-grid bar, a determinable grid, and point-in-time session and listing evidence all refuse under both requirements -- structurally, since those helpers take no `requirement` parameter and run before the branch. Only `_require_servable_coverage`, the availability check, sits behind it |
| 6 | The report's coverage came from the plan's declared scope | `PlannedCheck.applies_to` is a statement of intent. `universe_snapshot_header` and `adjusted_bar_artifact` were absent from `QualityContext.derived_records()` entirely, so no implementation ever received one and the report said both were covered. Derived records now include the headers and the artifacts; coverage comes from `CheckImplementation.subjects(context)` -- what the implementation was actually handed -- and an implementation the runner skipped covers nothing, with its governed reason recorded |
| 7 | Nothing recorded the standard a build was judged by | The checks read a profile resolution, approved bounds, evaluation cutoffs, a universe rule, market thresholds and a survivorship policy, all caller-supplied and none in the report's identity: two runs over one build under one plan with different thresholds produced interchangeable evidence. A canonical `quality_context_hash` covers every one of them plus the runner, the plan, the registry identity and `dataset.build_identity`. It enters the report's identity **and** the dataset manifest's, and the verified read refuses a stored report judged to a different one |
| 8 | Publication accepted a `QualityReport` carrying a copyable token | It takes a sealed `RunnerOutcome` instead -- unforgeable, unassignable, and produced only by running the plan. A hand-built report can still be constructed, because adversarial tests need one, and there is now no route by which it reaches publication. The outcome and the report each record the context, so a report substituted into an outcome stops agreeing and is refused |
| 9 | The rebuild check compared membership content only | Everything else in the header went unchecked: the considered listings that produced no row, the required-domain coverage, the evaluation cutoff, the rule's actual thresholds. The check now rebuilds the **complete header** and compares `header_identity_hash`. A `UniverseDefinition` version string was a promise that two builds used one rule and nothing verified it, so the header carries `universe_definition_hash` over the rule's parameters as well as its name |
| 10 | The adjustment convention was implemented two ways at once | `FORWARD_BASE_NORMALIZED` expresses every bar in the original base, so a factor applies to bars **on or after** the ex-date. The on-demand path did that; the materialised path excluded actions effective before the interval, and the same 2019-06-28 bar came back `104.000000` from one route and `52.000000` from the other. There is no lower bound on relevance, and now only one convention. `as_of_epoch` is normalised into the artifact key, so one instant in two zones is one artifact |

`MANIFEST_VERSION` stays **5**: this round changed what a run records about itself, not the
schema it records it in.

**What running the new checks found.** Two integration tests were asserting a read-path refusal
that the completed rebuild check now catches earlier, at publication -- the tamper never reaches
a reader. Both were rewritten to assert the publication-time refusal, and the read-path checks
they had been reaching are exercised directly and labelled defence in depth. Binding the
narrative to the query immediately caught the manifest fixture itself, which declared a
2019-06-24..2021-01-05 backtest window over a query that served five days of June 2019.

## 15. Query and evidence atomicity applied in revision 5

Revision 4 bound each artifact to what it was about. This round closes the places where a
**result** was still assembled from parts that could be substituted, or shortened without
saying so.

| # | Gap | Closure |
|---|---|---|
| 1 | A price series checked completeness **before** point-in-time filtering | Physical coverage was necessary and never sufficient: a bar that existed but was not yet publishable left the result, so a five-bar request came back four bars long with nothing to say so. Completeness is now checked **twice against one expected endpoint grid** -- against the stored rows, and again against what survived origin eligibility, availability resolution and the `as_of` cutoff. A `REQUIRED` series losing an endpoint to either is refused, the refusal names which of the four reasons applies to each, and where the served rows are a genuine prefix it names the `end` that would answer. `SeriesRequirement.OPTIONAL` accepts a labelled short series; neither is a default, because accessor parameters here never are |
| 2 | A universe snapshot was selected by UTC date and then filtered row by row | Both halves were wrong. Truncating an instant to a UTC date made a session a candidate at a moment when, in its own venue's terms, it had not opened; candidacy is now decided by the session's own `evaluation_cutoff`, an absolute instant. Filtering rows individually produced a membership set that had existed at **no instant**; candidates are now tried latest-first and the first available **in its entirety** is served, falling back to the whole earlier snapshot rather than part of the later one, and refusing when none is complete |
| 3 | The inventory conflated source datasets with derived artifacts | A universe query reads a **stored derived artifact**. Recording `universe_membership` as a directly-read source dataset made the manifest demand provider-resolution evidence for a table no resolution produces evidence about. A universe query now records the snapshot's full derived identity and no source dataset; a RAW price query records `price_bar` alone and no revision view, because it reads no corporate actions; an ADJUSTED query records both, requires an explicit `revision_view`, and applies it per action so a corrected and an uncorrected revision cannot both reach the arithmetic |
| 4 | An `InputInventory` built from evidence and one written by hand were the same type | So the manifest accepted a shortened one on sight -- internally consistent, which is exactly why it passed. `ExecutedResult` binds the result, its exact bytes, the execution evidence, the publication identity and the quality identity into one value only the reader can produce. `emit_manifest` takes it and cross-checks the manifest **against what the run recorded**: the result hash three ways, the quality-report identity, the itemised exclusions and the bounds actually used |
| 5 | The plan said what should run; nothing established that anything did | `checks_run` was a tuple of strings a caller supplied, so writing out every check id satisfied the plan completely with nothing invoked. A `QualityRunner` holds a registry of implementations, invokes them, and builds the report itself: `checks_run` from actual invocation, `checks_not_run` only from an applicability decision **the runner computed from the build**. A REQUIRED check with no implementation refuses, and so does a plan that marks one REQUIRED while naming none. The rebuild check genuinely rebuilds. Publication accepts only a runner-produced report, checked after the plan so a wrong report still fails for being wrong |
| 6 | Replay checked `dataset_version` **after** matching | Given two immutable builds of one listing, matching on the logical key found both, the uniqueness rule fired first, and replay refused as ambiguous against lineage that named exactly one of them. Version now selects the candidate; uniqueness is evaluated inside the named build, where a genuine duplicate still refuses |
| 7 | The empty-history sentinel proved nothing | Version `"none"` with an empty endpoint list resolved to an empty tuple whatever the store held. A no-history claim now names a governed window, the publications it was established against, and the **profile** it was established under -- the last because the rule saw the admissible set, and testing the claim against every stored row refuses builds that were right. Replay searches, and a bar inside the window refuses |
| 8 | The header named considered listings only when nothing qualified | Precisely backwards: the evidence for "this security was looked at and did not qualify" appeared exactly when nothing qualified, and vanished the moment one other security did. The header now always names both halves -- every decision's exact lineage and every considered listing state -- plus the build's own required-domain coverage. The verified read replays that lineage and holds every row to its header on session, definition version and profile |
| 9 | The adjusted artifact took its source versions from the caller | Two scalars, unverified, while an exact lineage can span several immutable builds. Both are now **tuples derived from the resolved rows**, and an artifact whose claimed versions disagree with what resolved is refused -- previously such a claim was ignored rather than caught. Corporate-action replay keys on `(action_id, dataset_version)`. The interval boundary was off by one case: the convention applies a factor on or after the ex-date, so a split whose ex-date **is** `valid_time_start` scales the first bar, and excluding it left the numbers and the lineage agreeing while both contradicted the convention |
| 10 | `MANIFEST_VERSION` did not move when the identity inputs did | Now **5**. The version identifies the implemented schema, and the implemented schema changed. Retaining 4 because an earlier planning example named it would have been the wrong way round -- the document describes the schema, not the reverse -- and no production Phase-3 manifest exists to migrate |

**Running the checks for real found three things.** Two were mistakes in how they were registered:
the stored-shape check was handed whole encoded rows rather than their envelopes, and the
profile-service check was handed every stored row rather than the servable ones. The third is a
real gap in the reference fixture, reported as two warnings (limitation 14).

### What adversarial review of revision 5 then found

Each closure above was handed to an independent reviewer instructed to break it. Twenty-six
candidate holes were reported and **seventeen confirmed real**. All are fixed; none is
outstanding. They fall into three groups, and the pattern is worth stating because it is the same
one every round: a check that measures a claim against something *adjacent* to it.

**Half a question is not a question.** Coverage checked that every expected endpoint had a bar and
never that every bar was expected, so deleting one calendar row -- or flagging it a holiday --
shrank the grid past a genuine gap and a refusing query began returning a hole in the middle.
Listing rows were the one input never filtered point-in-time, so a delisting published in 2020
decided which sessions a 2019 query expected. And ``withheld_endpoints`` documented an invariant
the code did not enforce.

**A seal over descriptions is not a seal over the thing.** ``VerifiedPublication`` sealed the
manifest, report and receipt hashes -- none of which is about the rows -- so ``dataclasses.replace``
carried a genuine seal onto a dataset whose rows had been removed. The quality report proved the
checks ran and not what they ran over, so a clean build's report published a defective build.
``build_identity`` now covers the source and membership rows themselves.

**A gate that takes its own standard from the caller is not a gate.** Publication accepted the
caller's ``QualityPlan``; the runner accepted a caller's registry; the rebuild check skipped
sessions the caller did not declare a cutoff for; the manifest compared consumed artifacts by id
while every field that makes one reproducible went unchecked; and findings whose id no planned
check owned were silently dropped.

## 16. Evidence closure applied in revision 4

Revision 3's enforcement was real, but several checks compared a claim to something *adjacent* to
it rather than to the claim itself. Each row below is a way the previous code would have said yes.

| # | Gap | Closure |
|---|---|---|
| 1 | The receipt was keyed on row **names** | A source-row identity now carries entity, source dataset version, source id, vendor record id, logical primary key, revision sequence **and the row's full canonical content hash**. A corrected price or a revised availability time under the same `source_id` changes the fingerprint. Publication checks the row fingerprint, the evidence fingerprint, the policy version, and every evidence entry's policy and stated reason against the canonical map. The read **recomputes the whole receipt** from the manifest, the persisted evidence and the rows it decoded -- the earlier read reconstructed one with empty fingerprints, which could only ever agree with itself |
| 2 | Lineage named the **Gold** version as every source version | A Gold build stores a *copy* of a row, and a copy does not become the source. Every selector now carries `row.envelope.dataset_version`, and a history spanning several immutable source versions produces one reference per version rather than one that averages them. An empty history is recorded explicitly, so "no prior bars" stays distinguishable from "unrecorded" |
| 3 | A reader accepted three objects passed side by side | `read_published_dataset` returns a **`VerifiedPublication`** carrying a seal over the manifest, the report and the recomputed receipt, and only the verified read path holds the token that constructs one. A hand-assembled triplet's hashes agree with *each other*, which is not agreeing with storage -- and that is exactly what the old constructor checked |
| 4 | A report said what ran; nothing said what **should** have | A versioned **`QualityPlan`** declares the expected check ids, which are REQUIRED and which may be declared not-run, each check's dataset scope and its closed finding vocabulary. Validation is a closed comparison: run ∪ not-run must equal expected, disjoint, no duplicates; every finding must belong to a check that ran and fall inside its scope; every published table must be covered; every required policy version must be present. The plan is looked up **by version on read**. The manifest also binds the **exact persisted report bytes**, because the logical hash omits `produced_at` by design |
| 5 | The snapshot header was an unattributed row count | It is a derived artifact: lineage, first-built time, spec version, content hash, `SESSION_SCOPED` validity, and a `header_identity_hash` covering session, definition, profile, cutoff, status, row count, membership hashes and lineage. The read verifies identity, `COMPLETE` status, row agreement, content hash and stamped dataset version. Under `FORWARD_SYSTEM` a snapshot is **not served before `artifact_first_built_time`** -- the zero-row case has no membership rows to carry that constraint on its behalf |
| 6 | Two different adjusted artifacts could share one key | The key now covers the validity interval, the source `BarResolution`, and exact canonical **price-bar and action lineage hashes** alongside policy, convention, profile, `as_of`, source dataset versions, spec version and scope. Bar lineage names exact endpoints per security per source version rather than a scope-and-range predicate, and verification resolves the recorded selectors, checks their versions, **rebuilds the key and the id**, and recomputes from only those rows |
| 7 | "Repaired" was inferred from circumstance | An acquisition has a durable state: `PENDING` record, then content, then `COMPLETE`. `repaired=True` now requires completing a pre-existing `PENDING` identity. A new run id over content the store already holds is `content_written=False, acquisition_written=True, repaired=False` -- an ordinary second fetch, which used to be logged as a recovery event. Acquisition identity is **globally** unique, and an idempotent rewrite still verifies the stored bytes |
| 8 | Internal filenames were matched by prefix | `write_staged_bytes` accepts an **exact allowlist** of this package's own files; `_dataset_manifest.json/../../escape` also begins with an underscore. Components ending in a dot or space, and Windows device names (`CON PRN AUX NUL COM1-9 LPT1-9`) at any extension, are refused on every platform -- a store written on one is read on another |
| 9 | The inventory arrived through side channels | The verified query path records what it reads as it reads it and hands out an immutable `ExecutionEvidence`; `InputInventory.from_execution` builds the inventory from that. `emit_manifest` no longer takes `unapproved_bounds_relied_upon` or `hash_mismatches` -- the only party who could have reported them was the one with a reason not to. The result hash covers the **exact bytes** rather than a decoded string, and emission cross-checks the quality-report identity, the origin-exclusion count and the bounds against the resolution evidence |
| 10 | `TimingBasis` said `EXACT` on zero exact rows | An axis with rows applicable and none retained reports `NONE_RETAINED`, which is neither `EXACT` (a basis derived from nothing) nor `NOT_APPLICABLE` (no row on the axis existed). Survivorship takes its horizon from the **build's own** `build_time` -- the manifest's, after a verified read -- rather than a caller-supplied cutoff, counts only `listing_end > S and <= horizon`, and requires deep-history snapshots that actually selected members |
| 11 | The minute **accepting** path was tested at the grid function | A full regular session (390 endpoints) and a half day (210) are generated from the venue calendar, published, verified on read and served whole -- exact count, first and last endpoint. Omitting one endpoint refuses the series; recording the half day as an ordinary session refuses a genuinely complete one, which is what proves the grid comes from the calendar rather than from the bars |

## 17. Enforcement closure applied in revision 3

| # | Gap | Closure |
|---|---|---|
| 1 | Gold accepted arbitrarily assembled rows | `resolve_run_inputs` issues a **ResolutionReceipt** hashing the profiles, the complete policy map *with reasons*, the evidence and every resolved row's identity. `build_gold_dataset` is the only sanctioned constructor, and publication refuses a receipt that does not account for the rows. A row filed under the wrong dataset key, or appearing in two groups, is refused at the boundary |
| 2 | `BOUND` could be declared without resolving | After the policy runs, every surviving row must have a **resolvable** provider time. A bound whose derivation is not approved resolves nothing, and that now refuses with `4.3.2_unresolved_provider_availability` rather than passing because the policy name looked right |
| 3 | Quality was not a gate | A typed **QualityReport** — policy versions, checks run, checks *not* run, findings with content hashes — is required at publication, bound into the manifest by hash, persisted, and re-verified on read. `open_issues=()` is gone: a reader takes the report the publication was gated on, so there is no evidence to omit |
| 4 | Publication identity was partial | `manifest_hash` covers format version, identity, coverage, both profiles, the global resolution, the whole resolution map and evidence, the receipt and report hashes, every table record, ingestion runs, commit and policy versions. Reads additionally verify coverage ordering, UTC build time, unique entities and datasets, non-negative and coherent counts, expected table paths, and actual row counts |
| 5 | Bronze content was filed per acquisition date | Split namespaces: content under `objects/sha256/<digest>`, acquisitions under `acquisitions/<provider>/<dataset>/<date>/`. Identical bytes on different dates share one object; a second acquisition is not a repair; a contradictory acquisition identity is refused; the audit verifies JSON, digest linkage, byte count, partition identity and content existence; writes fsync the containing directory |
| 6 | Lineage replay ignored the dataset version | Every resolved record's `dataset_version` must equal the one its `LineageRef` names — the same key in a later build can carry a corrected value. Selector shape is validated against an exact key set, duplicate and unordered bar endpoints are refused, and malformed values arrive as `ArtifactIntegrityError` rather than a raw parse error |
| 7 | Required-input and universe semantics were incomplete | A domain never supplied is as unavailable as one filtered to nothing. Missing security-type evidence is `REQUIRED_INPUT_UNAVAILABLE`, never a `SECURITY_TYPE` exclusion. Overlapping attribute rows and contradictory listing revisions refuse. `CHANGE_ANNOUNCEMENT` is not a listing state. A **UniverseSnapshotHeader** records that a session was built, so a genuinely zero-row snapshot survives write and read |
| 8 | Price coverage was under-specified | `as_of` is normalised at every accessor boundary. Coverage is per **exchange** (a NASDAQ security is not required to have NYSE sessions) and per **resolution**: daily expects one bar per listed trading session; minute follows the dense contract and requires the session's whole endpoint grid, so one arbitrary bar cannot pass. A required series emptied by ineligibility refuses with `REQUIRED_INPUT_UNAVAILABLE` |
| 9 | The adjustment convention had a default | `AdjustmentMode` enforces RAW ⇒ no convention and ADJUSTED ⇒ both policy and convention, with no default anywhere. The reader inspects it, refuses an unsupported one, passes it to the implementation and records it in provenance. Artifact lineage names **only** the actions the policy consumes, for the scoped securities, effective inside the declared interval — an ignored action would otherwise narrow the artifact's availability for a row that changed nothing |
| 10 | The manifest trusted caller-supplied lists | A typed **InputInventory** owned by the manifest replaces `directly_read_datasets=[]` and friends. `emit_manifest` verifies closure against it and against the actual result bytes, and refuses duplicate references, non-canonical artifact times, and a dataset read at a publication other than the one referenced |
| 11 | Survivorship counted the wrong evidence | Only a `STATE` row whose `listing_end` falls on or before the dataset horizon counts. Announcements and post-horizon endings do not. Year subtraction is leap-day safe, and `SurvivorshipPolicy` now validates its own thresholds — the minimum is **2**, because the documentation says one snapshot is an anecdote |

Per-axis resolution evidence accompanies 1 and 4: a dataset holding both authoritative-public and
provider-derived rows has a different denominator per axis, so the evidence records applicable,
exact, bounded, excluded **and unresolved** counts per axis. One shared `rows_considered` made the
axes fail to reconcile on every mixed dataset.

## 18. Corrections applied in revision 2

| # | Defect found | Correction |
|---|---|---|
| 1 | An empty `FORWARD_SYSTEM` universe was published as a valid artifact | The build refuses with `REQUIRED_INPUT_UNAVAILABLE` when a supplied REQUIRED domain empties; a genuinely empty *selection* still publishes, with reasons (§6) |
| 2 | `ProfileResolutionConfig` was audit-only and never touched the rows | `resolve_run_inputs` is the execution boundary: `BOUND` writes the bound before evaluation, `EXCLUDE` removes rows, `NONE` over a gap refuses by check name, and the Gold build consumes only resolved rows |
| 3 | `get_price_history` could mix resolutions and silently truncate | `resolution` is a mandatory keyword-only parameter; range, coverage, security-existence and series-completeness are validated before serving, with four distinct outcomes |
| 4 | Every membership row carried every admissible input as lineage | Lineage is exact and per security — one listing revision, one attribute row, that security's own bars — and the content hash covers the whole decision. Readback replays the selectors and refuses missing, broader, narrower or contradictory lineage |
| 5 | Gold writes were not atomic and reads trusted caller-supplied metadata | Staging plus a single-rename commit, a dataset manifest with per-table hashes, and reads that verify every table before decoding. Bronze separates content from acquisition and repairs an interrupted acquisition |
| 6 | Limitation tokens were emitted from declared configuration | Tokens come from evidence: bounded rows, excluded rows, positive origin exclusions. `emit_manifest` also refuses a wrong schema version, a non-UTC cutoff, duplicate evidence, a mismatched dataset profile, a missing revision view, missing consumed-artifact evidence, and a mutable definitions mapping |
| 7 | Instants could retain arbitrary offsets | One `normalize_instant`, applied in every envelope, entity and manifest constructor. `12:00:00Z` and `07:00:00-05:00` produce identical canonical values, stored bytes and hashes. Dates stay dates |
| 8 | The survivorship alarm faulted any snapshot with no delistings | Scoped by a versioned `SurvivorshipPolicy`: only deep-history snapshots are eligible, and the domain-wide alarm needs a minimum number of them. A recent snapshot with no delistings yet passes |
| 9 | A session-date assertion was disabled by `or True`; import scanning missed relative and aliased imports; SDK checks depended on the local virtualenv | The assertion compares against the calendar; the scanner resolves relative imports at every level and sees through aliases, with its own fixtures; SDK checks read project metadata and KalpaMani's own imports |
| 10 | The adjustment convention was unnamed | `FORWARD_BASE_NORMALIZED`, carried in the request, the artifact key, the derivation spec, the artifact row and therefore `run_id`. Building from zero bars, inadmissible bars, an unauthorized multi-security scope, or bars outside the declared validity interval is refused |

Deep-frozen mappings accompany 4 and 6: `GoldDataset.universe` and `ResearchManifest.definitions`
are wrapped in `MappingProxyType` at construction, so `frozen=True` does not merely wrap a dict
anyone can mutate after its hash was taken.

## 19. Verification

```
pytest                          1088 passed   (440 pre-existing, 648 new)
ruff check .                    clean
ruff format --check .           clean
mypy                            clean, strict, 93 files
scripts/phase1_preflight.py     exit 0
scripts/phase2_preflight.py     exit 0
scripts/phase3_docs_audit.py    exit 0
scripts/test_integrity_audit.py exit 0
```

Zero network access. Zero broker interaction. Zero provider credentials.

No Phase-1 or Phase-2 test was weakened. `data` left the bootstrap empty-by-design list because
its premise changed with this authorization, and was replaced by a **tighter** guard that names
the authorized A1 surface rather than only forbidding everything.
