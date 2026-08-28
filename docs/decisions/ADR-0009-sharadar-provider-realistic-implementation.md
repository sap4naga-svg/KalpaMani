# ADR-0009 — Sharadar Provider-Realistic Implementation Authorized (Slice 1, Code Only)

**Status:** **Accepted — effective on the merge of the pull request that introduces this ADR.**
Until that merge it is proposed and carries no authority.
**Date:** 2026-08-28
**Deciders:** Project owner (human governance)
**Supersedes:** the repository rule that **no production module may name a provider**, which was
correct while no provider-specific implementation was authorized. Nothing else. It does **not**
supersede any gate status, any recommendation in the
[G1/G3 decision packet](../phase3/provider-licensing-decision-packet.md), or any part of
[ADR-0005](ADR-0005-point-in-time-data-architecture.md).
**Superseded by:** —
**Relates to:** [ADR-0005](ADR-0005-point-in-time-data-architecture.md) (the gate model and the
point-in-time contract), [ADR-0007](ADR-0007-cloud-first-research-data-plane.md) (the private AWS
location and the deletion-first posture the object-store contract encodes),
[ADR-0008](ADR-0008-sharadar-personal-use-license-and-private-qualification.md) (the accepted
personal-use licence, and the privacy constraints on qualification output)
**Authority:** Blueprint V3.0 §17, §19 · CLAUDE.md §4.22, §4.23, §8

---

## 1. The decision

The owner issued the governance instruction:

> **"Authorize the next Sharadar implementation phase."**

This ADR records that decision. **Sharadar-specific, provider-realistic implementation is
authorized**, beginning with one narrow, code-only slice.

### What that authorization covers

| | |
|---|---|
| Sharadar-specific production-quality code | **authorized** |
| provider-neutral interfaces that code requires | **authorized** |
| deterministic request construction from **public** documentation | **authorized** |
| credential-**injection** interfaces (no credential value) | **authorized** |
| redaction, error hygiene, rate limiting, bounded retries | **authorized** |
| Bronze ingestion mechanics, content addressing, ingestion-run metadata | **authorized** |
| a provider-neutral `ResearchObjectStore` contract and an in-memory implementation | **authorized** |
| synthetic-only tests, package-boundary enforcement, documentation | **authorized** |

### What it does not cover — and each is a separate written authorization

```
purchasing a subscription       starting a free or paid trial      creating a vendor account
providing billing information   obtaining a private API key        storing a provider secret
mutating Secrets Manager        calling the Sharadar API           using the published test key to fetch
retrieving Services Data        production historical backfill     Silver or Gold real-data work
production universe build       building or pushing a container    running an ECS task
creating any AWS resource       terraform apply                    any AWS mutation
broker / IBKR / LEAN activity   Paper expansion                    live trading
```

**No request has been sent to the vendor by this work, and none may be.** The package this ADR
authorizes has never contacted Sharadar. A static test proves that importing it opens no socket,
that only one module is network-capable, and that **nothing in the repository constructs that
transport** — no runner exists, and none is authorized.

---

## 2. What this decision is **not**

Each line below is a distinct thing a reader could reasonably but wrongly infer from
"the next Sharadar implementation phase is authorized".

| | |
|---|---|
| **Not** final **G1** closure | provider selection / qualification remains **OPEN** |
| **Not** subscription authorization (**A3**) | no subscription is authorized, at any tier |
| **Not** purchase authorization | nothing may be bought, trialled or credentialed |
| **Not** production ingestion authorization | no Services Data may be retrieved or stored |
| **Not** a finding about the private qualification | see §3 |
| **Not** movement on ADR-0005 | it remains **PROPOSED** |
| **Not** a Phase-3 milestone | Phase 3 remains **NOT COMPLETE** |

### Implementation target ≠ production provider

The distinction is the whole point of this ADR, so it is stated plainly:

> **Sharadar is now the implementation target for provider-realistic Phase-3A integration work.
> Sharadar is not the selected production provider, because G1 is not closed.**

G1 cannot close while the two **pre-purchase** questions remain unanswered, and §5 records that
a fresh public-source pass on 2026-08-28 did not answer either of them:

- **Q7** — are the daily bars **officially disseminated** or **provider-aggregated**? A
  provider-aggregated answer makes `price_bar`, and the universe built on it, ineligible under
  `PUBLIC_PIT`.
- **Q8** — what depth does the **Full History** tier actually deliver, per table? Depth is the
  whole point of the tier, and it determines which tier, if any, is purchasable.

Building the adapter first is deliberate and costs nothing that a wrong answer would waste: the
request construction, the credential boundary, the redaction, the pacing and the Bronze mechanics
are all necessary whichever way Q7 and Q8 resolve, and none of them presumes an answer. What a
`PROVIDER_AGGREGATED` answer to Q7 changes is the **classification** of the resulting rows — a
Silver-layer decision this slice does not reach.

---

## 3. The private qualification evidence is not reproduced here

The owner reviewed the private Sharadar qualification evidence **inside the private licence
boundary**, and separately issued the governance instruction in §1. That instruction is the
governance input to this ADR, and it is sufficient.

Sharadar Terms §8 bars disclosing conclusions drawn from evaluating the Services or the Services
Data — not only publishing them, but disclosing them to any outside individual or entity — and
[ADR-0008](ADR-0008-sharadar-personal-use-license-and-private-qualification.md) §3 accepted that
constraint. Accordingly this ADR:

- **states no P1–P9 status**, reproduces no observation, and names no private recommendation;
- **infers nothing** about what the evidence showed from the fact that implementation was
  authorized. An authorization to build is not a published verdict, and reading one out of the
  other would be the disclosure §8 forbids, arrived at by implication;
- **speculates about nothing**, because a speculation that happened to be right would disclose
  exactly as much as a statement.

No AI session read the private report, its observations, its recommendation, any sampled vendor
row, or any licensed object. That constraint held throughout the work this ADR records.

---

## 4. What was built

Code only. No network call, no credential, no vendor data, no cloud mutation.

### 4.1 A provider-neutral object-store contract

[ADR-0007](ADR-0007-cloud-first-research-data-plane.md) anticipated an interface between the code
that *produces* an object and the code that *puts it somewhere*.
`src/kalpamani/data/objectstore.py` is that interface at the smallest production-worthy size:
`put_if_absent` and `exists`, over content-addressed logical objects.

**A producer knows no bucket, no cloud account, no ARN, no Terraform output and no SDK type.**
Those are deployment facts, and an adapter that knew one could not be tested without it — which is
how a unit test ends up needing credentials.

**Classification is part of an object's identity, not an attribute of it.** A logical key is
`<classification>/<segments>`. An object whose classification were merely a field could be moved
between the licensed and control stores by an ordinary-looking edit; an object whose
classification is part of its key cannot move without becoming a different object. That matters
because the licensed store is deletion-first under CLAUDE.md §4.23 and the control store is
precisely the material that must *survive* a deletion.

**LICENSED is structural.** `ObjectKey.licensed(...)` takes no classification parameter, so
provider-derived material cannot be routed elsewhere by omission, by a wrong keyword or by a
copied line. `ObjectKey.control(...)` exists and demands a written attestation that vendor rows
cannot be reconstructed from the object; a blank attestation is refused. This encodes ADR-0007's
rule that **uncertain resolves to LICENSED**.

**The real S3 writer is deliberately not in this slice.** It is the piece that needs a
credential, a bucket and an SDK, and it belongs immediately before authorized ingestion rather
than months ahead of it. The project still declares **no runtime dependency**.

### 4.2 Provider-neutral Bronze publication

`src/kalpamani/data/ingest/publication.py` publishes a payload byte for byte, named by the
SHA-256 of its contents, plus the record of how it was acquired. It has no HTTP client, no
credential and no vendor vocabulary, and a static test refuses the file if a vendor name appears
in it.

Two ordering facts are worth recording, because both were forced by the storage model:

1. **The payload is written first, the acquisition record second.** The record's existence is
   what marks an acquisition complete.
2. **The `PENDING`/`COMPLETE` two-phase pattern used by the filesystem Bronze writer is
   structurally unavailable here**, because an append-only `put_if_absent` store has no *replace*
   — a `PENDING` record could never be advanced. Record-last is the ordering that works under
   append-only semantics and is the safer of the two: an interrupted run can leave a payload
   nothing explains, which is detectable and inert, but it can never leave a record naming a
   payload that does not exist.

**No payload is parsed before publication.** A future response that is malformed, truncated or in
an unexpected encoding is still preservable as evidence — which is exactly the case where
evidence matters.

**Recorded metadata carries an allowlisted field set**, and a write is refused if any value
contains a credential, a URL, a query string or a cloud identifier. A caller-supplied note is the
realistic way one would arrive, so the guard runs on every publication rather than on the day
someone remembers it. The refusal names the offending field and never quotes its value.

The ingestion-run representation is the **existing** `IngestionRun` contract entity, not a new
one. A parallel vocabulary is a vocabulary that eventually disagrees with itself.

### 4.3 The Sharadar package

`src/kalpamani/data/ingest/sharadar/`, and vendor knowledge lives nowhere else.

| module | what it is responsible for |
|---|---|
| `credentials` | injection only. **No key value exists anywhere under `src/`** |
| `redaction` | closed error vocabularies, so a body has no parameter to arrive through |
| `datasets` | three Stage-3A tables, explicit windows, explicit pagination, no bulk download |
| `transport` | the only network-capable code, and dormant |
| `client` | pacing, bounded retries, byte-faithful fetch |
| `bronze` | translation into the neutral publisher, which owns every storage rule |

**Credential boundary.** No API key value appears in production code — not a private one, and
**not the vendor's published test token either**. The published token legitimately lives in the
manual qualification harness under `scripts/`; a value that is harmless in an owner-run probe
becomes a habit if production code carries one, and the habit is what eventually commits a real
key. A credential is injected, renders as a fixed placeholder through `repr`, `str`, f-strings,
`format` and `%`-formatting alike, and is reachable only through a method named `reveal()` so
every genuine use is one grep away. It is never logged, stringified, persisted in Bronze metadata
or attached to an exception. `credential_from_env` takes an **explicit mapping**, so this slice
has no route to the process environment and creates and reads no real secret.

**Request construction.** HTTPS only, a deterministic User-Agent, an explicit format, explicit
pagination, and an explicit date range on the two windowed tables. Every path segment and
parameter name is taken from the vendor's published query examples (`PSR-SHD-118`); nothing is
guessed.

Three refusals are load-bearing rather than defensive:

- **No implicit one-year window.** The vendor defaults `from` to one year ago and `to` to the
  prior day on every temporal table (`PSR-SHD-121`), so a request that omits them succeeds and
  means something narrower than the surrounding code claims. A windowed dataset without a window
  is refused.
- **No window on the snapshot table.** The vendor states `tickers` is a snapshot whose 5, 10 and
  full bulk options return the same table (`PSR-SHD-119`), so a date range there is a parameter
  attached to a table with no time axis.
- **No constructible table-wide bulk download.** `years=` fetches every security. It is on a
  forbidden list, absent from the parameter allowlist, and both are checked on every build.

Every request names exactly one security, so no shape here enumerates the market. A multi-symbol
form is not documented publicly, and inventing one would put an unverified parameter shape on the
wire the first time a real credential is used. How a full-universe backfill is actually assembled
is a decision for the authorized ingestion slice, on evidence this slice does not have.

**Error hygiene, and why it is built now.** The Sharadar key travels in the query string
(`PSR-SHD-109`), so a request URL *is* a credential, in full, in one string. Errors are therefore
**assembled from closed vocabularies** — a stage, a code, a pattern-checked dataset label — rather
than redacted after the fact. A response body, a URL and a key have no parameter to arrive
through. A vendor payload handed in where a dataset name belongs becomes `<unnamed>`. Textual
redaction exists as a second layer, and it matches any key rather than one known literal.

Response bodies are never read on a failing status: `urlopen` raises an exception that *is* the
response, and the transport closes it and returns the status with an empty body instead.

**Pacing and retries.** No public rate limit exists (`PSR-SHD-109`), and *no documented limit is
not an absent limit* — so the default is one request per second, with the clock and the sleep
injected so the pacing is provable without spending it. Retries are bounded (three attempts), on
a fixed backoff schedule with no jitter, and narrow: **an authorization refusal is not retried**,
because a rejected key is rejected every time and retrying turns one refused request into
several. A backoff subsumes the pacing interval rather than adding to it.

### 4.4 Boundaries, enforced by scan

ADR-0009 widened a rule; it did not remove one. Vendor knowledge is now allowed *somewhere*, so
"nowhere" stopped being the rule and something narrower took its place:

- the A1 point-in-time kernel and every vendor-neutral data package **must not import** the
  provider package, and neither may the neutral Bronze writers;
- research, strategy, risk and portfolio code cannot reach the ingest layer at all;
- **no production module outside the provider package names the provider**, so a second
  unreviewed integration cannot appear beside this one;
- the provider package does not reach the brokerage boundary, the point-in-time query layer, or
  the private qualification harness;
- **no external-AI path exists** for a vendor payload;
- importing the package opens no socket, only `transport` is network-capable, and nothing in the
  repository constructs it.

All are AST and text scans over committed files. None contacts Sharadar, AWS or any network.

### 4.5 Tests

Synthetic and hand-authored throughout. No vendor row, no vendor worked example, no sampled
response, no private qualification material. The fictitious payloads were never a CSV, because
Bronze treats a payload as opaque bytes and parsing one would test something this slice does not
do. The synthetic credential values announce in the value itself that they are fake.

---

## 5. Q7 and Q8 — public sources re-checked, both still unresolved

Re-read on **2026-08-28** from public pages only. **The vendor was not contacted, the API was not
called, no account was signed into, and nothing was purchased.** Recorded as `PSR-SHD-122` and
`PSR-SHD-123` in [provider-source-register.md](../phase3/provider-source-register.md) §R4.

| | |
|---|---|
| **Q7 — bar construction and origin** | **STILL UNRESOLVED.** Four public pages — stock-prices documentation, the FAQ, the prices product page and the vendor blog's launch post — describe *what* is delivered and *how it is adjusted*, and **none states how the bars are constructed or where they are sourced**. `PSR-SHD-098` stands, and the conservative `PROVIDER_DERIVED` classification with it. Not discoverable from the data either, which is why it is a question rather than a test. |
| **Q8 — Full History depth per table** | **STILL UNRESOLVED**, and now more precisely bounded. The subscribe page still lists *5 Years / 10 Years / Full History* and **still does not define Full History**. |

The Q8 pass did resolve one thing and open another, and both are recorded because they do not cut
the same way:

- **Resolved by attribution.** The apparent 1998-vs-1999 conflict is partly a mis-reading: the
  launch post's *"since 1999"* describes **fundamental data**, not prices. That is a narrowing of
  the discrepancy, not an answer to Q8.
- **A new discrepancy.** The prices product page states *"History back to December 1998"*, while
  the stock-prices documentation states **January 1998**. Two vendor pages, two start dates for
  one table. Small, and exactly the kind of imprecision that makes "what does Full History
  actually deliver" a question worth answering **before** money changes hands rather than after.

**Neither question was invented an answer.** Both remain **pre-purchase blockers**. Neither
blocks this code-only slice, because nothing here presumes an answer to either.

---

## 6. Decision-gate map after this ADR

**Unchanged by this ADR.** It closes no gate and opens none.

| Gate | Subject | Status |
|---|---|---|
| **G1** | provider selection / qualification | **OPEN** |
| **G2** | production information-set profile | **OPEN** |
| **G3** | vendor licensing — Sharadar personal use | **CLOSED (2026-08-27, ADR-0008)** |
| **G4** | analyst estimates and revisions | **OPEN** |
| **G5** | historical borrow | **OPEN** |
| **G6** | options overlay | **OPEN** |
| **G7** | strategy-taxonomy evidence | **OPEN** |

If the provider changes away from Sharadar, **G3 reopens for the replacement provider**
(ADR-0008), and this ADR's implementation authorization does not transfer to it.

---

## 7. Explicit non-authorizations

| | |
|---|---|
| Sharadar selected as the production provider | **NO** — G1 is open |
| Subscription authorized (A3) | **NO** |
| Purchase, trial or vendor account authorized | **NO** |
| Private provider credential authorized | **NO** |
| Any provider API call authorized | **NO** |
| Services Data retrieval or storage authorized | **NO** |
| Production ingestion / historical backfill authorized | **NO** |
| Silver or Gold real-data work authorized | **NO** |
| Real S3 writer authorized | **NO** — a following reviewed slice |
| Any AWS mutation, image build or task run authorized | **NO** |
| ADR-0005 status changed | **NO** — remains **PROPOSED** |
| Phase 3 complete | **NO** — remains **NOT COMPLETE** |
| Broker, IBKR, LEAN or Paper expansion authorized | **NO** |
| Live trading | **HARD-DISABLED** |

---

## 8. Consequences

**Positive.** The provider boundary now exists as reviewed, tested code rather than as a plan, and
it was built at the one moment when it *could* be built calmly: before a credential exists, before
a bill is running, and before a schedule depends on it. The redaction and credential boundaries in
particular are worth far more written now than written in a hurry beside a live key. Q7 and Q8
being unresolved cost the slice nothing, because none of what was built presumes an answer.

**Negative, and stated plainly.** The code is unexercised against the real API, so a documented
parameter that behaves unexpectedly will not be discovered until a first authorized fetch. That is
the accepted price of building before purchasing, and it is bounded: every request shape is
sourced from a public vendor example rather than guessed, and the whole surface is three tables.

**A rule the repository must keep.** "No production module names a provider" was a clean,
checkable rule and it is now gone. Its replacement — vendor knowledge inside one package, named
nowhere else — is only as good as the scan that enforces it, which is why that scan is a test
rather than a paragraph.

---

## 9. Review

Reviewed with the pull request that introduces it. Accepted on merge; until then it carries no
authority.
