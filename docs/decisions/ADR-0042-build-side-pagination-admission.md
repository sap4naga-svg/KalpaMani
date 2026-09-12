# ADR-0042 — Build-side pagination admission: one supported page shape for every dataset

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0042 is proposed and carries no authority.
That is a statement about the present, it will remain true of these days after any later merge, and it
is not to be rewritten as though this decision had authority before it was accepted. On merge, this ADR
becomes **ACCEPTED / IN FORCE** as **a narrow amendment of ADR-0041 §3's pagination clause and of
ADR-0040's truncation rule — one supported page shape, applied to `tickers`, `actions` and `stocks`
alike, with a closed refusal vocabulary — and nothing else**, effective together with the offline
gate merged beside it. **Acceptance authorizes no execution** (§5).

**The condition above has since been satisfied.** **PR #99 merged** — merged **2026-09-12T18:15:35Z**, merge
commit **`9d2bacc0095ad540bfc5b0bc351f51bfb09582dc`**, ordered parents **`5d4ecd766fa9fcb8ab3fc1c2e3bf77e49a67cc92`** then
**`622fec5496dd782f83844e3982993e5e9d4a6ca6`**, with a **merge tree identical to the independently reviewed pull-request head
tree** (`d1c0cd4322d9b2f789d857a91af2df98dd35c7d4`). ADR-0042 is therefore **ACCEPTED / IN FORCE** as a narrow
amendment of ADR-0041 §3's pagination clause and of ADR-0040's truncation rule, effective together with the
offline gate merged beside it. While the pull request was open it was proposed and carried no authority —
true then, and not rewritten. **Acceptance authorizes no execution.** One accepted, non-blocking diagnostic
discrepancy is recorded with the merge: for a group shaped `[short, empty, non-empty, empty]` the merged gate
returns `PAGINATION_UNSUPPORTED` where §2 above reads `PAGINATION_INCONSISTENT`; both refuse the whole
build before any write, and no correction was part of that merge.

**Nothing was run to produce this decision.** No AWS call, no Terraform plan or apply, no credential
retrieval, no provider request. The evidence is the merged build path exercised on synthetic fixtures
and the vendor's public documentation recorded in the provider-source register (`PSR-SHD-129`,
`PSR-SHD-133`).

---

## 1. Context — what a COMPLETE locator proves, and what the build accepted

[ADR-0041](ADR-0041-production-provider-request-form.md) §3 recorded that the vendor documents offset
pagination but neither a terminal-page signal nor a stable order across offsets (`PSR-SHD-133`), declared
a non-empty second page of a **one-session cross-section** unsupported, and deferred the build-side refusal
to a later change. [ADR-0040](ADR-0040-research-build-output-objects-and-manifest.md) clause 3 and the
merged build refused only a **final page at the limit** (`DELIVERY_TRUNCATED`).

Reproduced through the real modules before this change, the merged build **published** every one of
these deliveries as `COMPLETED` with eight writes: a full first page followed by empty pages; a full first
page followed by a non-empty page of unique rows; a short first page followed by a non-empty later page;
an empty first page followed by data on the second; and a full first page of repeated rows followed by an
empty page — on `tickers`, `stocks` and `actions` alike. Each carried a COMPLETE acquisition locator, which
is the point: **a COMPLETE locator proves that every compiled request has confirmed publication
dispositions. It does not establish the semantic completeness of the vendor's answer to a window, and an
empty terminal page does not establish stable ordering or snapshot consistency across the earlier
pages** — it proves only that no rows remained beyond the last offset asked for.

## 2. Decision

**Every group of parsed pages — one acquisition run, one dataset, one exact compiled window — must be the
one supported shape, or the build refuses:**

```text
group          (run_id, dataset, window) from the pages' own compiled coordinates; never combined across
               runs or windows; every compiled ordinal present and exact (the accepted locator validator)
supported      offset-zero page: fewer RAW data rows than its requested limit
               every later compiled page: present, validly parsed, header-only
measured       raw parsed row counts, before deduplication, revision consolidation, symbol mapping or
               filtering -- a full page of repeated rows is a full page
empty group    every page header-only: pagination-consistent and NOTHING MORE; the calendar,
               completeness, identity and empty-result rules downstream still apply
where          in the build, after integrity, provenance and parsing, before consolidation and before
               any Silver, Gold or manifest write
refused        PAGE_OVER_LIMIT            a page carrying more rows than its requested limit
               DELIVERY_TRUNCATED         an offset-zero page at or above its limit -- truncated / full-page
                                          uncertainty; an empty later page does not rescue it
               PAGINATION_UNSUPPORTED     a non-empty page at a positive offset, for all three datasets,
                                          whatever the rows look like -- multi-page delivery
               PAGINATION_INCONSISTENT    an empty earlier page followed by a non-empty later one, or
                                          offsets outside the compiled 0, limit, 2*limit, ... sequence
effect         one refused group refuses the whole input: zero Silver, Gold and manifest writes, no
               successful build result, and the read, byte and operation counts as observed
```

Consequences:

1. **Nothing about requests changes.** The compiled plan's coordinates, offsets, limits, digests and the
   provider serialization are untouched; the second page stays the completeness probe the plan asks for.
   The acquisition actor stays opaque and write-only: nothing is parsed there and no read is added.
2. **Duplicate detection proves nothing here.** Unique rows across pages do not establish that no rows were
   omitted, and repeated rows do not shorten a full page; the gate reads raw counts and refuses on shape.
3. **The limits of the supported shape are stated.** It avoids reliance on multiple data-bearing offset
   pages. It does **not** establish vendor completeness of the window, the inclusivity of the window's
   dates (`PSR-SHD-129`), or the consistency of a snapshot delivered across several requests. The manifest
   records the policy version, the admitted and empty group counts per dataset, and an explicit
   `does_not_establish` list.
4. **The vocabulary is closed and minimal.** `DELIVERY_TRUNCATED` keeps its accepted name; the three new
   members separate observed structural inconsistency, unsupported multi-page delivery and a page over its
   limit. The gate's members map one to one onto the Silver refusal vocabulary, and a test asserts totality.
5. **Admitted inputs are unchanged downstream**: content digests, provenance, revision chronology,
   availability, membership, adjustment lineage and the action-gap rule apply exactly as merged.

## 3. Relationship to accepted text

- ADR-0041 §3 and §5 declared the one-session `stocks` case unsupported and the refusal deferred; this ADR
  implements the refusal and **extends it to `tickers` and `actions`**, whose pages rest on the same
  undocumented order. ADR-0041's text is unchanged.
- ADR-0040 clause 3's "a final page at the limit is `DELIVERY_TRUNCATED`" is superseded in effect by the
  first-page rule above: the last page's count is no longer what decides, and a full **first** page is
  refused whatever follows. ADR-0040's text is unchanged; it records what the build did on its merge day.

## 4. Rejected alternatives

- **Admit a second data-bearing page when its rows are disjoint from the first.** Disjointness cannot
  distinguish a stable partition from an unstable one that happened not to repeat a row.
- **Send `sort` for a stable order.** Forbidden by ADR-0009; it changes the byte stream.
- **Raise the page limit so one page suffices.** The documented maximum is unstated; a larger single page
  moves the uncertainty rather than removing it, and the compiled plan is not changed to make a gate pass.
- **Drop the refused group and publish the rest.** A partial dataset labelled complete is the outcome this
  ADR exists to prevent.

## 5. Effectiveness and execution gates

- **Effectiveness**: in force only on the independently reviewed merge of the pull request introducing it,
  together with the offline gate beside it.
- **Execution**: acceptance authorizes no build and no run; every ADR-0036 gate stays closed. Resolving the
  underlying limitation — a documented stable order, a terminal-page signal, or a plan amendment that
  requests one — is a separate decision with its own evidence, and no live request may be made to explore it.
- **Scope**: nothing here amends ADR-0009, ADR-0035, ADR-0036, ADR-0037, ADR-0038, ADR-0039 or ADR-0041's
  request form; the exchange calendar, split-ratio semantics, action-event identity, the task-side
  spent-identity source, the image and entry point, and R-3/R-5 stay unresolved.

G2 OPEN; CONTROL DEFERRED; Phase 3 NOT COMPLETE; live trading HARD-DISABLED.
