# ADR-0053 — Pagination v2: one governed data request plus one completion probe per group, multi-page data refused on evidence, qualified ceilings, and the whole-run replacement of acquisition run 1

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0053 is proposed and carries no authority.
That is a statement about the present, it will remain true of these days after any later merge, and it
is not to be rewritten as though this decision had authority before it was accepted. On merge, this ADR
becomes **ACCEPTED / IN FORCE** as **governance and contract only**: the owner's route decision of §0
recorded, the pagination-v2 contract of §2, the qualification gate of §3, the replacement and planning
consequences of §4, the deployment-impact statement of §5 and the dated amendments of §6 — and nothing
else. **Acceptance authorizes nothing that runs** (§7): no provider qualification request, no
implementation, no image build, no Terraform, IAM, tfvars or registration change, no acquisition launch,
no S10c build, no M0 backtest. **Every numeric limit and ceiling in this document is a candidate until the
qualification cycle of §3 has run and its evidence has been accepted** — none is qualified by this ADR.

**Nothing was run to produce this decision.** No AWS call, no STS call, no S3 operation, no provider
request, no image built or pulled, no credential retrieved. The evidence it rests on was produced under
two earlier, separately authorized read-only diagnoses recorded outside this repository (the eight
run-1 payload pages read through the accepted exact reader and parser on 2026-09-17/18); their sanitized
figures are restated in §1 and no licensed row, key or bucket name appears here.

---

## 0. The owner's decision, recorded verbatim

> I accept the R1 + R2 pagination-correction route: governed single-data-page acquisition with a
> completion probe, explicit refusal of multi-page data, raised bounded payload/parser ceilings, full O-5
> recompilation, and whole-run replacement of acquisition run 1. Existing run 1 remains historical
> evidence; run 2 and S10c remain on hold.

This decision:

- does **not** waive completeness, determinism, schema, licensing or evidence requirements;
- does **not** declare run 1 buildable;
- does **not** authorize provider qualification, implementation, deployment, acquisition, S10c or
  backtesting;
- preserves run 1 as historical acquisition evidence;
- preserves the superseded run-2 specification and its unconsumed identity;
- keeps runs 2–19 and S10c blocked.

## 1. Context — what the eight page reads established

The first production acquisition (O-5 run 1, identity `run-20260917T221453Z-af316f8b`, plan
`8920a050…`, `COMPLETED` exit 0, receipt-verified: 96 provider requests, 1 secret retrieval, 290
conditional writes) published a run locator that the accepted validator **admits** (65,169 bytes, SHA-256
`24f9c7be…`; every clause of ADR-0036 §2.4 and the 25 owner checks PASS). Reading its pages through the
accepted exact reader (`read_exact`: byte count and SHA-256 verified before a byte is returned) and the
accepted parser (`parse_payload`) established, per compiled group:

| group | pages (offset) | rows per page | terminal page | determination |
|---|---|---|---|---|
| `tickers` / SNAPSHOT | 4 (0, 10000, 20000, 30000) | 10,000 · 10,000 · 10,000 · 10,000 | **FULL** | **TRUNCATED** — ≥ 40,000 rows, the response continues beyond the compiled ceiling |
| `actions` / 2024-09-15–2025-09-15 | 2 (0, 10000) | 10,000 · 10,000 | **FULL** | **TRUNCATED** — ≥ 20,000 rows |
| `actions` / 2025-09-16–2026-09-14 | 2 (0, 10000) | 10,000 · 10,000 | **FULL** | **TRUNCATED** |
| `stocks` / 44 session windows | 2 each | 30 sessions below the limit; 14 non-session days and every page 2 header-only (70 bytes) | SHORT / EMPTY | complete-shaped |

Every page parsed with the same header digest within its dataset (`tickers` 28 fields; `actions` 7
fields, the accepted Route-A digest), zero exact-duplicate rows within any page, byte counts and digests
equal to the locator's. The accepted ADR-0042 gate refuses the tickers group `PAGINATION_UNSUPPORTED` and
would refuse every truncated group; the whole run-1 input is therefore **not buildable** under ADR-0042.

**The decisive additional finding.** Comparing the rows of tickers pages 3 and 4 in memory found **2,147
byte-identical rows present on both pages** (and none duplicated within either page). The vendor's
documented default order for the tickers table is `lastpricedate.desc` (`PSR-SHD-131`); every active
ticker shares the latest price date, and the order among tied rows is undocumented (`PSR-SHD-133`). The
same record was therefore served at two different offsets seconds apart — and, symmetrically, records were
omitted. **Offset-based assembly of several data-bearing pages is not stable enough for deterministic,
complete assembly under the accepted request form**, whatever the build does with the pages. (The 7,879
repeated `(permaticker, ticker)` keys across those pages are structural: the vendor's table carries one
row per ticker per `table` value; and the 25 / 34 repeated `(ticker, date, action)` keys in the actions
windows, with zero repeated full rows, are several events per ticker-day, not overlap.)

The compiled plan (ADR-0035 §3.1 as implemented; `PAGES_PER_WINDOW` tickers 4 / actions 2 / stocks 2 at
`PAGE_LIMIT` 10,000) stored exactly the planned requests; the acquisition actor parses nothing and cannot
iterate. The accepted request model caps `limit` at `MAX_PAGE_LIMIT = 10,000` (ADR-0009, "the largest page
the vendor documents"), while the vendor documents `limit` with a default of 10,000, **no stated
maximum**, and one example at `limit=100000` on the tickers page (`PSR-SHD-131`). An example is not a
documented maximum and is not qualification (§3).

## 2. Decision — the pagination-v2 contract

**Effective on the merge of this pull request as the governing contract for production acquisition
planning and build-side admission; implemented by a later, separately authorized code cycle (§7); its
numeric constants fixed only by the qualification cycle of §3.**

1. **Multi-page data is prohibited.** Offset-based concatenation of two or more data-bearing pages of one
   group or window is refused — in the plan, in the locator and at the build. The recorded tickers overlap
   (§1) proves that the current offset ordering is not stable enough for deterministic assembly; this is a
   finding of fact, not a policy preference, and it is not lifted by an empty terminal page.
2. **One data request and one completion probe per group.** Each independently paginated dataset group
   or window is acquired by **exactly one governed data request at limit `L`** and **exactly one
   completion probe at offset `L`**, carrying the **same** table, filters, date bounds, ordering,
   projection and every other immutable request parameter as the data request. Nothing else is requested
   for that group.
3. **The data response may contain fewer than, or exactly, `L` rows.**
4. **The completion probe must parse successfully and contain zero data rows.** A header-only
   representation is permitted **only when the accepted parser proves zero rows**; a body the parser
   cannot parse is not "empty".
5. **A data-bearing, malformed, schema-incompatible or unparseable completion probe means the delivery is
   incomplete.** The acquisition **fails closed** and **does not publish a `COMPLETE` locator**; the
   build refuses such a group with zero writes.
6. **The completion probe is retained and hashed** as delivery-completeness evidence (a payload object,
   its acquisition record and its claim, exactly like a data page) and **contributes no rows** to any
   Silver, Gold or manifest artifact.
7. **Schema equality is required** between the data response and its completion probe: identical
   delivered header (equal schema digest), or the group is refused.
8. **Rows inside the single data page must satisfy the governed primary-key and uniqueness rules** of
   the dataset's accepted contract (the parser's exact-duplicate accounting and Silver's identity rules);
   a tickers snapshot with a repeated full row is refused.
9. **Provider duplicates are never silently removed** unless a separately accepted contract defines the
   deterministic key, the precedence rule, the evidence recorded and the resulting digest. No such
   contract exists; none is created here.
10. **A full data page (exactly `L` rows) followed by an empty completion probe may be admitted as
    complete.** This supersedes ADR-0042's `DELIVERY_TRUNCATED` refusal of an offset-zero page *at* its
    limit, because under v2 the probe — not the row count — is the completeness evidence.
11. **A full or partial data page followed by a data-bearing completion probe is refused as truncated**
    (`DELIVERY_TRUNCATED`): more rows exist beyond `L`, and they are not fetched by paging.
12. **Any plan or locator describing multiple data-bearing pages for one group or window is refused
    under v2** — the plan compiler emits exactly two requests per group (data at offset 0, probe at
    offset `L`), the locator validator refuses more, and the build refuses `PAGINATION_UNSUPPORTED` as
    today.
13. **Limit and payload qualification gate.** The numeric production limit `L` per dataset and every
    response, read, parse, row and memory ceiling are **conditional on the separately authorized
    qualification cycle of §3** and are **not fixed by this ADR**. It is not claimed that `limit=100000`
    is supported because it appears in a vendor example. The present 16 MiB response ceiling
    (`MAX_RESPONSE_BYTES`) is **visibly insufficient** for a single large tickers response — the four
    observed 10,000-row pages total ≈ 12.5 MB and the response continues — and **no replacement (64 MiB or
    any other value) is invented or finalized here**. If no safe single-page `L` exists for a dataset, the
    fallback is a **deterministic server-side partition by a stable predicate or key** (for example a
    documented filter that partitions the table into disjoint, individually single-page groups, each with
    its own probe); **offset pagination does not return as the fallback**.

**One bounded change to the acquisition actor's opaque boundary follows from rule 5**, and it is stated rather
than implied: the acquisition entry, which today parses nothing, must run the accepted parser on the **completion
probe response only** to prove zero rows (and equal schema, rule 7) before it may confirm the group and publish a
`COMPLETE` locator; any other result halts the run as `ACQUISITION_HALTED` after the probe's own three
conditional writes, with the locator `PARTIAL`. **Data responses stay opaque** — never parsed, never inspected
task-side; the probe check adds no read and no listing, and it is one parser invocation per group.

Unchanged by v2: the acquisition actor stays write-only and parses no data response; the locator stays
`COMPLETE` only with confirmed dispositions for every compiled request; content-addressed payload
identity, claims, records, reservation and locator-last ordering (ADR-0036/0037/0038/0040) are untouched;
the build's integrity, provenance, schema-admission, revision, availability, membership and manifest
rules apply exactly as merged; `does_not_establish` keeps vendor completeness, date inclusivity and
snapshot consistency across requests.

## 3. The qualification cycle — separately gated, and what it must establish

Before any constant is fixed, one bounded, separately authorized **provider-qualification cycle** must
run under the accepted personal-use licence and the governed principals, and record, for each candidate
`L` and each affected dataset (`tickers` snapshot; `actions` canonical one-year window; `stocks`
one-session cross-section, expected unchanged):

- whether the provider **accepts** the candidate `L` (HTTP success, no silent truncation, no error body);
- the **actual row counts** of the qualification data responses for tickers and actions;
- that the data response contains **fewer than `L` rows**, and that the probe at offset `L` is **empty**
  (parsed, zero rows, equal schema);
- the **response sizes and SHA-256 digests** of every response;
- **parser performance** (wall time, and that the parser's row and byte ceilings admit the response);
- **peak process memory** for reading, hashing and parsing the largest response;
- **task CPU, memory, ephemeral-storage and timeout sufficiency** for the acquisition and build task
  definitions (the compiled 1,800 s acquisition deadline and the 3,600 s build deadline included);
- **provider and personal-use licence compliance** of the qualification requests (bounded count, no
  redistribution, evaluation results private);
- a **documented safety margin** for the response-size and memory ceilings derived from the measured
  values, not asserted.

The qualification cycle's request count, principals, storage location and evidence contract are stated by
its own authorization (proposed in §8); it is **not** an acquisition run and produces no build input. Only
after its evidence is accepted may a code cycle fix `L`, the response ceiling, the read/parse ceilings and
the row ceiling, and only then may O-5 be recompiled (§4).

## 4. Replacement and planning consequences (recorded now; effective on merge)

- **Run 1** (`run-20260917T221453Z-af316f8b`) remains **valid historical acquisition evidence** —
  `COMPLETED`, receipt-verified, locator admitted, its 290 objects immutable — and is **not buildable**.
- The **tickers snapshot and both actions windows** (2024-09-15–2025-09-15, 2025-09-16–2026-09-14)
  **require reacquisition**.
- Because the accepted same-run snapshot mapping is atomic — Silver resolves each run's `stocks` rows
  through the `tickers` snapshot acquired in the **same run** (ADR-0035 §3.5 as implemented by the accepted
  build: `silver._snapshot_mapping` keyed by `run_id`) — **run 1 is replaced as a whole** by a new run under a new identity and the recompiled plan.
- **Stocks are not copied into, or patched onto, the old run.** No later ADR proving the immutable
  identity and digest semantics of such a patch exists; none is proposed here. Byte-identical stocks
  payloads re-acquired by the replacement run land as `ALREADY_PRESENT` under their content-addressed
  names, with their own new claims and records — no storage is duplicated and no old object is touched.
- The **expected replacement shape** is approximately **94 requests** — 88 stocks (44 session windows ×
  data + probe), 2 tickers (data + probe) and 4 actions (2 windows × data + probe) — but **the final count
  depends on qualification and recompilation** (a partition fallback under §2.13 adds groups).
- **If the final request count is 94, the conditional-write ceiling is `1 + 3 × 94 + 1 = 284`** (one
  reservation, one claim + one payload + one record per request, one locator last).
- **The complete O-5 program and every affected plan digest must be recompiled** after the qualified
  constants are accepted (`PAGES_PER_WINDOW`, `PAGE_LIMIT` and `MAX_RESPONSE_BYTES` are part of every plan
  digest); candidate C's digest `8920a050…` and run 2's `21680fc9…` describe the superseded plan.
- The **current run-2 specification** (`launch-specification-20260917T232613Z-cd5b10b9.json`, digest
  `899f2e11…`, identity `run-20260917T232613Z-28726d37`) remains **superseded and preserved**: no D-15
  was issued, no reservation, no launch, the identity unconsumed and not reused.
- **G1, G4, G5, PEAD, short-side and M0 readiness are unchanged** by this decision.

## 5. Deployment impact — corrected, and subject to later declaration-level verification

An earlier offline proposal said configuration digests "remain unchanged because the ceilings are code
constants". **That claim is withdrawn.** The accepted S1 compiled-configuration digest (ADR-0044 §2,
`CompiledTask` v2) binds the release **commit**, the exact **tree** and the generated **timestamp** of the
compiled-configuration file, so a new release normally moves the configuration digest **even when the
semantic configuration inputs are unchanged**. The expected impact of implementing v2, each item to be
verified at the declaration and registration steps rather than assumed:

1. **Rebuild four images** — acquisition, acquisition-verification, build, build-verification — from the
   merged implementation commit.
2. **Generate four new release-bound configuration digests** (one per rebuilt image), superseding
   `0c69c917…` (acquire) and the build's current digest for the new revisions.
3. **Probe images unchanged** unless later code analysis proves the permission-probe entry is affected
   (it does not parse or plan; expected untouched — to be shown, not assumed).
4. **Replace the four affected ECS task definitions** (new revisions) by a separately authorized Terraform
   plan and apply.
5. **Update both launcher policies** to the new exact revision ARNs (each launcher permission set is
   scoped to exact revisions — ADR-0036 §2.9).
6. **Reissue the four affected registration blocks** in the owner's launch inputs (new registration
   digest; `a0155d0a…` becomes historical for those targets).
7. **Registration-bound permission evidence becomes historical** for the replaced targets.
8. **Rederive the precise Terraform add / change / destroy count from the declaration** at plan time
   rather than assuming "four".
9. **Rederive which S9 and permission cells require repetition** under the new registration by applying
   the accepted registration-binding rules (ADR-0045 §7 — G-12 re-verification, ADR-0046 §2.3, ADR-0047). The likely repetition
   is the **six R-1 cells** and the **dedicated R-2 corroboration and isolation path** (ADR-0052). **It is
   not stated here that R-3 or the permission-probe evidence remains current**; each is decided by the
   binding rules against the new registration when it exists.

## 6. Amendments to accepted decisions (dated 2026-09-18; effective only on the merge of this ADR)

Each amended ADR receives a dated amendment section that preserves its historical text and marks the
superseded rule; nothing earlier is rewritten.

| ADR | superseded rule (historical, stays in the text) | rule under ADR-0053 |
|---|---|---|
| ADR-0009 | `MAX_PAGE_LIMIT = 10,000` as "the largest page the vendor documents" bounds every request | the production form's `limit` ceiling `L` is a **qualified** per-dataset constant fixed by §3; the qualification `SharadarRequest` form and its 10,000 ceiling are unchanged |
| ADR-0041 §3 | pagination as compiled offset pages transmitted as `skip`; page counts per window compiled | exactly one data request (offset 0, limit `L`) and one completion probe (offset `L`, same parameters) per group; multi-page data refused; `skip` still transmits the probe's offset |
| ADR-0042 §2 | one supported shape: offset-zero page **below** its limit + header-only later pages; a first page at its limit is `DELIVERY_TRUNCATED` | one data page of `≤ L` rows + one parsed empty probe of equal schema; a **full** data page with an empty probe is complete; a data-bearing probe is `DELIVERY_TRUNCATED`; multi-page data `PAGINATION_UNSUPPORTED` on evidence; schema mismatch and within-page duplicates refused; the label discrepancy of ADR-0042 §5 resolved as `PAGINATION_INCONSISTENT` |
| ADR-0035 §3.1 | request planning with fixed page counts per window (4 / 2 / 2) at 10,000 | data + probe per group at qualified `L`; windows unchanged unless the partition fallback of §2.13 applies; the same-run snapshot mapping of §3.5 (as implemented) confirmed as the reason run 1 is replaced whole |
| ADR-0043 §2 / ADR-0036 §2.2 | the acquisition entry composes the opaque processing path: nothing is parsed task-side | the acquisition entry parses the **completion probe only** (accepted parser; zero rows; equal schema) before confirming a group; data responses stay opaque; a failing probe halts before a `COMPLETE` locator |
| ADR-0040 §2 | manifest pagination record per ADR-0042 (`sharadar-pagination-admission-v1`) | `sharadar-pagination-admission-v2`: per group the limit `L`, data rows, probe result, schema equality, `rows_total == data_rows`, the probe's digest recorded as completeness evidence |

## 7. What acceptance does not do

Acceptance of this ADR performs and authorizes **none** of: a provider request (qualification included),
runtime implementation, an image build or publication, a Terraform plan or apply, an IAM, tfvars or
registration change, a permission probe, an acquisition launch, D-15 creation, S10c or any build, M0 or
any backtest, a decision on PR #119 / D-17 or on D-1, or any alteration of prior raw evidence. Run 2 and
runs 3–19 stay on hold; S10c stays blocked; run 1 stays historical evidence. **The next owner decision
after this merge is the bounded provider-qualification authorization of §8.**

## 8. The proposed bounded qualification authorization (for the owner to issue; not issued here)

One cycle, under the accepted personal-use licence, the governed acquisition principal and a fresh
`probe-`/qualification identity that never becomes a build input: for each candidate `L` the owner names
(the vendor's documented example value is the natural first candidate, **as a candidate**), **at most one
data request and one probe** per affected dataset — tickers SNAPSHOT; one canonical actions year window;
one stocks session — i.e. **at most six provider requests per candidate `L`**, published write-only under
a qualification namespace with claims, records and a locator like a production run, then read back once
through the accepted exact reader and parser to record the §3 measurements (row counts, sizes, digests,
parser time, peak memory), plus the task-resource observations from the receipt and the task definition.
Zero retries; a refused or truncated candidate is recorded and the next candidate needs its own
authorization. No result of that cycle is a build input, a provider verdict or a licence statement.

## 9. Revised cycle estimate (counts at the observed cadence; no dates)

Acquisition resumption: **≈ 8 bounded cycles** — this governance merge; the qualification authorization
and run (§8); the constants and v2 code cycle (plan, request form, pagination, silver, manifest, ceilings,
regressions); image builds and registration; Terraform/task definitions and verification; S9
re-verification under the new registration; O-5 recompilation and the run-1′ preparation; the run-1′
launch with its locator read and validation. First observation build: **≈ 10** (S10c authorization over
run 1′ after its validation). First M0 backtest: **≈ +20–25** after the first build (the remaining runs
of the recompiled program, their builds, G-8 and the M0 authorization).

## 10. Review

This ADR changes documentation, governance metadata, docs-audit support and governance tests only. It
changes no production runtime behaviour, no image, no configuration, no Terraform and no registration.
Every number it carries is either measured evidence (§1), an accepted contract fact, or an explicitly
unqualified candidate (§2.13, §3, §8).
