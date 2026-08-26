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
| the Phase-3A entity subset | `data/contracts/entities.py` |
| canonical serialisation and content hashing | `data/contracts/canonical.py`, `serde.py` |
| the reproducibility manifest and deterministic `run_id` | `data/contracts/manifest.py` |
| immutable content-addressed Bronze | `data/ingest/bronze.py` |
| Silver normalisation | `data/normalize/silver.py` |
| local analytical storage | `data/storage.py` |
| adjustment proof, historical-universe proof, Gold build/read | `data/curate/` |
| deterministic quality checks | `data/quality/checks.py` |
| point-in-time accessors | `data/pit/accessors.py` |
| synthetic reference dataset | `tests/fixtures/phase3a.py` |

Roughly 7,000 lines of source and 4,200 lines of tests and fixtures.

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
<root>/bronze/<provider>/<dataset>/<ingest_date>/<sha256>.json.gz
<root>/bronze/<provider>/<dataset>/<ingest_date>/<sha256>.meta.json
<root>/silver/<dataset_version>/<entity>.jsonl
<root>/gold/<dataset_version>/<entity>.jsonl
```

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

### A recorded consequence, not a defect

`FORWARD_SYSTEM` **cannot build a 2019 universe from reference data first seen in 2026.** The
snapshot is legitimately empty. That is exactly why the contract calls the profile mandatory for
forward validation and never valid for long histories — and why quietly serving the `PUBLIC_PIT`
answer instead would be the bug rather than the fix. A test asserts the empty result.

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

## 8. Synthetic fixture coverage

Four fictitious securities, an invented calendar, invented prices, and no clock anywhere:

- a continuously listed common stock, and the split-adjustment proof built on it
- a ticker rename (`KTHN` → `KTHX`) where identity survives
- a security delisted 2019-06-28: **present** in the 2019-06-27 snapshot, **absent** afterwards
- a ticker (`OBSQ`) legitimately recycled by a different security in 2021 — which must **pass**;
  only an *overlap* is a defect, and that adversarial variant is tested separately
- a regular session, a **half-day** session, and two distinct **minute bars** in one session
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

## 12. Verification

```
pytest                        630 passed   (440 pre-existing, 190 new)
ruff check .                  clean
ruff format --check .         clean
mypy                          clean, strict, 72 files
scripts/phase1_preflight.py   exit 0
scripts/phase2_preflight.py   exit 0
scripts/phase3_docs_audit.py  exit 0
```

Zero network access. Zero broker interaction. Zero provider credentials.

No Phase-1 or Phase-2 test was weakened. `data` left the bootstrap empty-by-design list because
its premise changed with this authorization, and was replaced by a **tighter** guard that names
the authorized A1 surface rather than only forbidding everything.
