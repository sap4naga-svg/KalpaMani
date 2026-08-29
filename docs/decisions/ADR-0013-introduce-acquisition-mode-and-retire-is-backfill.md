# ADR-0013 — Introduce Acquisition Mode and Retire is_backfill

**Status:** **Accepted — effective on the merge of the pull request that introduces this ADR.**
Until that merge it is proposed and carries no authority.
**Date:** 2026-08-28
**Deciders:** Project owner (human governance)
**Supersedes:** the **live `is_backfill` contract semantics only** — in
[ADR-0012](ADR-0012-implement-the-dormant-sharadar-qualification-runtime-core.md) §4 and wherever
else an accepted ADR describes that boolean as the current acquisition metadata. It supersedes
**no gate status**, no part of [ADR-0005](ADR-0005-point-in-time-data-architecture.md),
[ADR-0007](ADR-0007-cloud-first-research-data-plane.md) or
[ADR-0011](ADR-0011-implement-the-licensed-s3-research-object-store.md), and no authorization
boundary. **Accepted ADRs are not rewritten**: their historical text keeps the retired identifier as
the record of what was decided then, and none of it functions as a current contract.
**Superseded by:** —
**Relates to:** [ADR-0005](ADR-0005-point-in-time-data-architecture.md) (the point-in-time contract
and the gate model), [ADR-0009](ADR-0009-sharadar-provider-realistic-implementation.md) (the
provider bridge this changes),
[ADR-0010](ADR-0010-accept-bounded-sharadar-semantics-and-authorize-qualification-subscription.md)
(Q7 and Q8, unchanged by this),
[ADR-0012](ADR-0012-implement-the-dormant-sharadar-qualification-runtime-core.md) (the dormant
runtime, and the blocker this closes on merge)
**Authority:** Blueprint V3.0 §11, §17, §19 · CLAUDE.md §4.21, §4.22, §4.23, §4.24, §8

---

## 1. Context

The provider-neutral acquisition metadata carried one boolean, `is_backfill`, described in the
neutral layer as distinguishing *"a vendor backfill from an update"*.

That is a complete description of production ingestion and an incomplete description of what this
system does. A **qualification** retrieval — a bounded fetch whose purpose is to judge whether a
provider's data behaves as documented — is neither. **A qualification retrieval is not an
`UPDATE` because it is not an incremental production refresh. It may add qualification evidence,
but it does not advance an approved production dataset.** It is not an authoritative historical
load either, so calling it a backfill overstates what the evidence is. A two-valued field forced
it to claim to be one of them.

The distinction is about *production state*, not about emptiness. "Extends no prior state" would
have been the wrong reason: a qualification run may well write evidence, and the first production
`UPDATE` against an empty dataset extends nothing either. What separates them is whether the
operation advances an approved production dataset.

ADR-0012 recorded this as a **pre-execution blocker** and chose `False` as the value that could not
be mistaken for authoritative historical loading, while stating plainly that the fit was wrong and
that a real qualification run could not be authorized until the contract could describe one.

This ADR is that contract change.

---

## 2. Decision

**Replace `is_backfill: bool` with a closed `AcquisitionMode` vocabulary of exactly three members.**

| Member | Meaning |
|---|---|
| `QUALIFICATION` | A **bounded provider-validation retrieval**. Evidence gathered to judge whether a provider's data behaves as documented |
| `BACKFILL` | **Historical production loading** |
| `UPDATE` | **Incremental production refresh** |

**Three members, and deliberately no fourth.** There is no `UNKNOWN`, no `NONE`, no generic
historical mode and no extension point. Each would be a place for a caller who had not decided to
record that they had not decided — and a durable record whose mode means *"we did not say"* is worse
than one that could not be written at all.

### What the mode is, and is not

**It states the governed intent of the retrieval operation.** It is **never inferred** — not from
dates, ranges, record counts, payload contents, first-seen times, prior coverage, the provider or
the dataset. A run that happened to return old rows is not thereby a backfill; a run that returned
few rows is not thereby an update. Those are *observations about what arrived*; this field is a
*statement about what was asked for*.

**It proves nothing on its own.** Not point-in-time admissibility, not public availability, not
provider availability, not row chronology, and not whether a provider silently supplied revised
historical rows. Specifically:

* `BACKFILL` **does not** grant earlier PIT availability. When a row could first have been known is
  decided by the availability envelope, not by what the operation was called.
* `UPDATE` **does not** establish that the returned rows contain no historical revisions. A provider
  may silently restate history inside an incremental response, and nothing about the mode detects
  that.
* `QUALIFICATION` identifies a bounded provider validation **only**. It does not select a provider
  and it does not qualify the data.

**The historical-coverage observation stays separate.** The data-quality rule that notices a run
whose valid-time coverage extends earlier than the prior run's minimum is an *observation about
late-arriving or newly-covered historical data*. It is evidence worth recording, and it is **not**
the declared mode: it neither sets it, confirms it, nor contradicts it. Before this ADR that rule
*set* `is_backfill`, which conflated an observation with a declaration.

### An intentional breaking pre-data correction

**No real Services Data has ever been ingested under the retired schema.** No provider API call has
been made, no Services Data has been retrieved, and no acquisition record exists outside synthetic
tests. So there is nothing to migrate and nothing to read back — which is precisely why this is the
moment to make the change, and why the change may be total.

**Nothing is retained for compatibility.** No default, no boolean-to-mode conversion, no inference,
no alias, no deprecated property, no legacy reader and no dual-write. The retired key is not in the
durable field allowlist, so a record carrying it — alone or beside the new field — is refused rather
than translated. Synthetic fixtures and tests were migrated because there was no real data behind
them.

### The single source of truth

`RetrievalMetadata.acquisition_mode` is **required, has no default, and is the only place the mode
is stated.**

| | |
|---|---|
| `RetrievalMetadata` | carries the mode; exact member only |
| `IngestionRun` | required and exact, **derived** from the retrieval — `build_ingestion_run` takes no second mode parameter |
| `BronzePublication` | does **not** carry it; it already carries the `retrieval` that does |
| `acquisition_record` | reads `retrieval.acquisition_mode`; no parameter |
| `publish_bronze_payload` | no parameter |
| the Sharadar bridge | **requires** an explicit mode when constructing neutral metadata |
| the qualification runtime | passes `AcquisitionMode.QUALIFICATION` directly, with no plan field and no caller override |

A second copy anywhere would be a second place to state one fact, and the interesting case is the
one where two copies disagree — which no validation can resolve, because neither is more
authoritative than the other.

### The durable record

```diff
- "is_backfill": false
+ "acquisition_mode": "QUALIFICATION"
```

* the field allowlist names `acquisition_mode` and **not** the retired key;
* the value serialised is a **plain exact `str` token**, never a `StrEnum` member — a record is
  bytes on a disk, and a `StrEnum` is a `str` *subclass* whose identity is not what a later reader
  gets back;
* validation admits exactly `QUALIFICATION`, `BACKFILL` or `UPDATE`, and refuses booleans, integers,
  `None`, wrong case, trailing whitespace, unknown tokens and the enum member itself;
* the filesystem Bronze record and the object-store Bronze record **agree on the shared
  acquisition fields** — provider, dataset, requested range, retrieved-at, source schema version,
  ingestion run id, content digest, byte count and `acquisition_mode` — with identical exact mode
  semantics on both. **Their envelopes are deliberately not identical** and no test asserts that
  they are: the filesystem record additionally carries `status`, `ingest_date` and `notes`
  because it completes in two steps and is repaired in place, and the object-store record
  additionally carries `classification` and has no free-text field at all. Both records are
  actually constructed and read back in tests — the filesystem one from a real store on disk,
  not from the builder that wrote it;
* the same acquisition identity with a **different** mode is a metadata contradiction and fails
  closed **on both storage paths**, proven against each; with the **same** mode and identical
  metadata it stays idempotent, and a refused attempt leaves the stored record byte-identical;
* claim → payload → acquisition-record ordering, append-only behaviour, payload bytes,
  classification, object-store security and CONTROL deferral are all untouched.

### Verification refuses what publication would have refused

**A record already on disk must be refusable by reading it.** Writing the mode is not the same as
checking it: the comparison that catches a contradiction runs during a *republish*, and a record
that is already wrong was never republished. So filesystem completeness verification —
`BronzeStore.audit_acquisitions`, and therefore `require_complete` — enforces the durable shape
itself:

| | |
|---|---|
| **exactly one active mode field** | `acquisition_mode`, present on every record |
| **exact built-in `str`** | not a `bool`, an `int`, a null or a `str` *subclass*. A subclass compares equal to its token and would otherwise pass an `in` test while being a different type |
| **exactly one of three tokens** | `QUALIFICATION`, `BACKFILL`, `UPDATE`. Wrong case, surrounding whitespace and unknown tokens are refusals, not near-misses to be normalised |
| **a closed field allowlist** | the record's key set must equal the durable shape exactly. A missing field is incomplete; an undefined field was written by something this repository does not know about |
| **no legacy-reader path** | no alias, fallback, conversion, inference, default or dual-read. A record written under the retired schema is **republished, never translated** |
| **no republish required** | the check runs on every record, before any early exit, so malformed durable metadata is discovered by reading the store rather than by attempting to write to it again |

**The retired key is refused by absence, not by a check that names it.** It is simply not in the
allowlist, so it lands among undefined fields — which is the stronger arrangement, because the
allowlist refuses *every* field it does not define rather than one anticipated name. What keeps it
out of the allowlist is the separate repository-wide guard forbidding the retired identifier
anywhere under `src/`. The two compose: the allowlist refuses what it does not define, and that
guard refuses any attempt to define the retired name. A record carrying the retired key alone, or
carrying it *beside* a valid `acquisition_mode`, is refused either way — the dual-written case
being the disagreement no validation could resolve after the fact.

**No record-controlled text reaches a message.** A malformed field's value is exactly what is least
safe to repeat into a log or a traceback, and an unrecognised field's *name* is uncontrolled too, so
undefined fields are counted rather than named. Everything a verification reason does name — the
required fields, the permitted tokens — comes from a module constant.

**There is no acquisition-metadata schema-version field, and `source_schema_version` is not one.**
That field describes the *provider's payload* schema, and repurposing it would make one value answer
two unrelated questions. Rather than invent an unrelated version field, this ADR records the
breaking pre-data correction and the exact durable shape is **pinned in tests** for every mode — so a
future change to it is visible rather than silent.

---

## 3. Alternatives considered

**Keep the boolean and document the qualification case.** Rejected — that is what ADR-0012 did, and
it produced a field that had to be explained every time it was read, plus a blocker preventing the
only operation the system could actually perform.

**Add a fourth `UNKNOWN` member.** Rejected. Every durable record is written by code that knows what
it is doing; a member meaning "we did not say" would be chosen by whatever did not want to decide,
and it would then have to be interpreted forever.

**Keep `is_backfill` and add the mode beside it.** Rejected, firmly. Two representations of one fact
is a dual-write, and the case that matters is the one where they disagree — which cannot be resolved
after the fact and would be discovered as a contradiction in stored evidence.

**Provide a compatibility reader that maps `false → UPDATE`.** Rejected, and it would be actively
wrong: `false` never meant `UPDATE`, it meant *"not a backfill"*, which under the retired vocabulary
included every qualification retrieval. A converter would manufacture a claim nobody made. There is
also nothing to read: no real record exists.

**Derive the mode from coverage.** Rejected. That is exactly the conflation being corrected: the
coverage rule observes what arrived, and the mode declares what was asked for.

---

## 4. Consequences

**Gained.** The contract can describe the only retrieval this system is able to perform. The mode is
stated once, by the party that governs the operation, and every durable record carries it in a form
a reader can check. Qualification evidence stops being labelled as a production operation.

**Given up.** Backward compatibility with a schema no real data was ever written under. That is a
cost only on paper.

**The `is_backfill` metadata blocker closes.** It closes **only when this ADR becomes effective on
merge and the complete removal is verified** — no live boolean, no alias, no converter, no default,
no dual-write, each proven by test rather than asserted here.

**Closing that blocker does not authorize or execute a real qualification run.** It removes one
obstacle that stood in front of asking for authorization. **Real Sharadar qualification remains NOT
AUTHORIZED and has never run**, and every other prerequisite is untouched: no credential, no
composition root, no client, no bucket binding, no runner.

**Not gained — stated exhaustively.** This ADR authorizes **code, tests, documentation and synthetic
validation only.** It does not authorize:

> credential retrieval, inspection, creation, setup, storage or binding · Secrets Manager · AWS
> session or client construction, binding, reads, mutations, verification or Terraform · bucket
> discovery or binding · any Sharadar API call · published-test-token probing · Services Data access,
> download, publication or ingestion · bulk download · empirical qualification · production backfill,
> update, backfill runner or production ingestion · CONTROL publication · provider selection or
> G1/G2 closure · broker, LEAN, Paper expansion or live trading

`BACKFILL` and `UPDATE` exist as production modes. **This ADR authorizes neither production
operation**; it only gives them names so that a qualification retrieval no longer has to borrow one.

**Unchanged.** **G1 OPEN · G2 OPEN · G3 CLOSED (Sharadar personal use, ADR-0008) · G4 OPEN ·
G5 OPEN · G6 OPEN · G7 OPEN.** ADR-0005 remains **PROPOSED**. INC-0002 remains **OPEN**. Phase 3
remains **NOT COMPLETE**. CONTROL publication remains **DEFERRED**. `LIVE_TRADING_HARD_DISABLED`
remains **True**.

---

## 5. Verification

Enforced by test, not by review:

| Property | How |
|---|---|
| exactly three members, in order, with no escape hatch | membership and cardinality assertions |
| exact-member enforcement on `RetrievalMetadata` and `IngestionRun` | twelve rejected values including both booleans, a `str` subclass and the wrong case |
| no default on any mode-bearing constructor or publication API | `dataclasses.MISSING` and `inspect.Parameter.empty` |
| the run's mode is derived, not passed | `build_ingestion_run` has no such parameter |
| the publication result does not duplicate it | field-set assertion |
| exact durable JSON for each of the three modes | whole-record pinning per store, plus an explicit comparison of the nine shared acquisition fields between a real filesystem record and an object-store record |
| the two envelopes differ only as intended | the filesystem-only and object-store-only field sets are named and asserted, not assumed equal |
| completeness verification refuses a missing mode | the field removed from a real record on disk; audit reports it and `require_complete` raises |
| every malformed durable mode is refused on its own | `"UNKNOWN"`, `"qualification"`, `"QUALIFICATION "`, `false`, `null`, `1`, each independently; a `str` subclass against the shape helper, where it is the only thing that can arrive |
| the retired key is refused alone and beside a valid mode | both records written to disk and refused |
| the field allowlist is closed | an arbitrary undefined field is refused, and the allowlist is asserted equal to the shape actually written |
| refusal needs no republish | `BronzeStore.write` is replaced with a raising stub for the duration; verification must not reach it |
| the refusal is a property of the bytes | restoring the exact original record byte-for-byte makes verification pass again |
| no record-controlled text is echoed | a canary value, and a canary *field name*, absent from both the audit reasons and the exception |
| the filesystem record carries the mode in both states | `PENDING` and `COMPLETE` bodies, read back from disk |
| the serialised value is a plain `str` | `type(...) is str` plus a JSON round-trip |
| the retired key is refused, alone and alongside the new one | allowlist assertions |
| no executable module names the retired identifier | AST scan over `src/`, docstrings stripped |
| no alias, property, converter or dual-write exists | class and source scans |
| the mode is never derived conditionally | AST scan for conditional expressions assigned to it |
| counts, ranges, payloads, datasets and timestamps do not change it | one retrieval built with three wildly different shapes |
| the qualification runtime emits only `QUALIFICATION` | published records inspected; `BACKFILL`/`UPDATE` absent from its code |
| the qualification runtime's mode is unreachable from `QualificationPlan` and from the runtime's execute caller | dataclass fields and constructor signatures |
| a neutral synthetic caller can construct all three | parametrised publication |
| same identity, changed mode → refused; same mode → idempotent | both storage paths, both directions. The filesystem record is compared byte-for-byte before and after; the object store is snapshotted whole — every logical key, its payload and its admitted digest — and compared after the refusal |
| write ordering, `LICENSED` classification and PIT rules survive | unchanged assertions, re-run for every mode |

**Every test is synthetic and offline. Nothing here contacts a provider, AWS or a network, and no
credential, bucket, endpoint or real-data path becomes constructible.**

### 5.1 A defect this ADR's first revision contained

Recorded because it is the reason several rows above exist, and because a correction that hides
what it corrected teaches a later reader nothing.

**The first revision of this change updated the object-store acquisition record and left the
filesystem one behind.** `RetrievalMetadata` carried the mode and `acquisition_record` emitted it,
but `_acquisition_body` still returned the pre-migration shape, so the filesystem Bronze store
recorded **no mode at all**. Worse, because `_require_same_retrieval` compares every recorded field
except `status`, restating one acquisition identity under a **different** mode was **accepted rather
than refused** on that path — the exact contradiction this ADR claims fails closed.

**Nothing caught it, and the reason is instructive.** The test named as the local/object-store
comparison compared `acquisition_record` against the store that `acquisition_record` had just
written: both sides came from the object-store builder, and no test in the suite constructed a
filesystem record at all. A whole suite can pass while a storage path is entirely unexercised, and a
test's *name* is not evidence of its subject.

The fix is one field, because the machinery that refuses the contradiction already existed and only
needed the mode to be present to compare. The tests are the substantive part: a real `BronzeStore`
on disk, records read back as bytes rather than as builder output, the shared fields compared across
the two stores, the envelope difference named, and the changed-mode refusal proven on both paths.

### 5.2 A second defect, in the same shape

Writing the mode is not checking it, and the second revision fixed the writer without noticing that
**nothing verified**. `audit_acquisitions` — and therefore `require_complete` — validated JSON,
status, digest linkage, byte count and partition identity, and said nothing whatever about
acquisition metadata. A COMPLETE record on disk could carry no mode, an unknown or non-string mode,
the retired key instead of the new field, or both keys at once, and completeness verification passed
it.

**The failure mode is the same one twice: a property enforced on one path and assumed on another.**
First the object-store record was updated and the filesystem record was not; then the filesystem
record was written correctly and nothing read it back. In both cases the contract was stated in the
ADR and true of exactly one code path.

The correction is the closed allowlist and the mode checks described in §2 above, running on every
record before any early exit. What makes it more than a third instance of the same mistake is that
the refusal no longer depends on a second party doing the right thing: verification reads the bytes
that are actually there, and a test replaces `BronzeStore.write` with a raising stub to prove the
refusal never routes through publication.
