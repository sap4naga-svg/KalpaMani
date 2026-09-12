# ADR-0041 — The production provider request form: ticker-less snapshots and cross-sections

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0041 is proposed and carries no authority.
That is a statement about the present, it will remain true of these days after any later merge, and it
is not to be rewritten as though this decision had authority before it was accepted. On merge, this ADR
becomes **ACCEPTED / IN FORCE** as **a narrow amendment of ADR-0009's request model — one additional,
explicit request form beside the accepted one — and nothing else**, effective together with the offline
adapter merged beside it. **The offline adapter that accompanies this proposal is likewise proposed and
offline until that merge, and acceptance authorizes no execution** (§5).

**The condition above has since been satisfied.** **PR #98 merged** — merged **2026-09-12T17:38:46Z**, merge
commit **`5d4ecd766fa9fcb8ab3fc1c2e3bf77e49a67cc92`**, ordered parents **`2be8d2ee7946de457e8071160f89836746713168`** then
**`db5b950bc1ff377fae4773c15efb14ee0fa051be`**, with a **merge tree identical to the independently reviewed pull-request head
tree** (`a1ee6800875a95036f15f790a7ddf02c168274ba`). ADR-0041 is therefore **ACCEPTED / IN FORCE** as a narrow
amendment of ADR-0009's request model, effective together with the offline adapter merged beside it. While the
pull request was open it was proposed and carried no authority — true then, and not rewritten. **Acceptance
authorizes no execution**: the only transport the adapter has been handed is a scripted fake, and the build-side
refusal §3 and §5 deferred was **not implemented by that merge** — it is proposed separately
([ADR-0042](ADR-0042-build-side-pagination-admission.md)).

**Nothing was run to produce this decision.** No AWS call, no Terraform plan or apply, no credential
retrieval, no provider request of any kind — not a "test" request, not the published test key. The
evidence is the accepted request model in code, the compiled production plan, and the vendor's public
documentation recorded in the provider-source register (`PSR-SHD-118`, `PSR-SHD-119`, `PSR-SHD-121`,
`PSR-SHD-129` to `PSR-SHD-133`).

---

## 1. Context — the conflict, traced in code

[ADR-0009](ADR-0009-sharadar-provider-realistic-implementation.md) accepted one request model,
`SharadarRequest` (`ingest/sharadar/datasets.py`): **every request names a ticker** (`ticker` is a
required field held to a symbol grammar, and `build_query_parameters` always transmits it), the only
date filter is an explicit `from`/`to` window on the windowed tables, the snapshot table refuses a window,
and the transmitted names are held to a closed allowlist `{api_key, format, ticker, from, to, limit, skip}`.
That model is right for what it was accepted for: a bounded, single-subject qualification probe.

[ADR-0035](ADR-0035-initial-breakout-long-research-dataset-ingestion-design.md) §3.1 designs production
acquisition as **ticker-less cross-sections**: a full `tickers` snapshot per run, `actions` in canonical
windows, and `stocks` one session at a time. The compiled production plan (`production/sharadar/plan.py`)
emits exactly those coordinates — `(dataset, window, page_offset, page_limit)` with no subject — and the
acquisition processor hands each to an injected `ProductionProvider`. **No implementation of that protocol
could reach the accepted transport**: constructing a `SharadarRequest` without a ticker is refused at
construction, so PR #96 and PR #97 recorded the incompatibility as an owner decision rather than widening
the accepted model.

The reported reading — that production needs a `date` equality filter the model lacks — is not what the
plan needs. A session cross-section is already expressed as a one-day window (`from = to = session`),
which the accepted allowlist can carry. **The one thing the accepted model cannot express is a request
with no ticker.**

## 2. What the public documentation establishes, and what it does not

Recorded in the register with URLs and access dates; summarized here. *Documented* means stated on the
page; *assumed* means the page is silent and the plan names the consequence.

| Point | Documented | Assumed / unsupported |
|---|---|---|
| Endpoint and format | `https://api.sharadar.com/v1.0/data/<table>`; `format` csv or json (`PSR-SHD-118`) | — |
| Ticker-less requests | `ticker` defaults to `all` on `stocks`, `actions` and `tickers`; ticker-less `from`/`to` examples are shown (`PSR-SHD-129`, `PSR-SHD-130`, `PSR-SHD-131`) | — |
| Date filters | `from`/`to` on `stocks` filter the trade date, on `actions` the `date` field; on `tickers` they bound **`lastpricedate`** and there is no default window (`PSR-SHD-129`, `PSR-SHD-130`, `PSR-SHD-131`) | **inclusivity of `from`/`to` is not stated**; the plan reads `from = to = d` as "session `d`" and a window as closed on both ends |
| Pagination | offset pagination: `limit` (default 10000) and `skip` (default 0, alias `offset`) (`PSR-SHD-129`) | **no terminal-page signal and no documented stable order across offsets** (`PSR-SHD-133`); the compiled plan's numeric offsets *do* map to the vendor's `skip`, so no translation is invented |
| Ordering | default `sort` is `date.desc` (`stocks`, `actions`) and `lastpricedate.desc` (`tickers`) (`PSR-SHD-129`, `PSR-SHD-130`, `PSR-SHD-131`) | `sort` stays **forbidden** (ADR-0009): a sorted delivery is a different byte stream |
| Page-size limit | `limit` default 10000; a `tickers` example requests 100000 (`PSR-SHD-131`) | **no maximum stated**; the compiled plan keeps its own 10000 ceiling |
| Errors, throttling, truncation | **not stated** (`PSR-SHD-132`) | classified by HTTP status through the accepted closed vocabulary; one attempt; a truncated body is refused by the transport's byte ceiling, a full page by the build's truncation rule |

## 3. Decision

**A second, explicit request form exists beside the accepted one, and neither changes the other:**

```text
SharadarRequest        accepted (ADR-0009), unchanged: ticker REQUIRED; window required on stocks/actions,
                       refused on tickers; parameters api_key, format, ticker, [from, to], limit, skip
CrossSectionRequest    proposed here: NO ticker; window required on stocks/actions, refused on tickers
                       (their from/to bound lastpricedate and would narrow the universe); parameters
                       api_key, format, [from, to], limit, skip -- in that fixed order, and nothing else
allowlist              CROSS_SECTION_PARAMETER_ALLOWLIST = QUERY_PARAMETER_ALLOWLIST - {ticker};
                       the accepted allowlist and the forbidden set are unchanged; no name is added
filters                none beyond the window: no action, contraticker, permaticker, table, status,
                       fields, sort, years, lastupdated; a filtered cross-section is a different dataset
format                 csv, fixed by the plan (the acquisition record's source-schema version names it)
pagination             limit = the compiled page_limit (1..10000); skip = the compiled page_offset;
                       the compiled offsets are transmitted as the vendor's skip -- no translation
validation             the same closed-member normalization, exact Page and DateWindow types and
                       windowed/snapshot rule as the accepted form, applied at construction
serialization          canonical: the fixed parameter order above; URL = API root / dataset ? query;
                       HTTPS required; the credential appears only in the query (PSR-SHD-109)
```

**The production adapter** (`production/sharadar/provider.py`, `SharadarProductionProvider`) is the one
`ProductionProvider` implementation that reaches the accepted transport. It compiles a
`ProductionRequest` into a `CrossSectionRequest` — refusing, **before any transport invocation**, an
unsupported dataset, a window on the snapshot, a snapshot on a windowed table, a malformed window or a
malformed page — and hands it to the accepted `SharadarClient`, whose single fetch loop (`_fetch_url`)
now serves both forms. The client is bound to **one attempt** and a **zero-interval pacer**: the
acquisition processor already paces on the compiled interval and admits every request against the run
deadline, so the adapter adds no retry and no second pacing. The transport's origin pinning, redirect
refusal, timeout, byte ceiling and credential redaction are the accepted transport's and are untouched.
The adapter counts **actual transport invocations**; a local refusal is zero, and the acquisition
report's `provider_requests` is read from that count.

**A third client construction site, named.** ADR-0014 put the accepted client's construction in the
qualification composition root and ADR-0019 in the empirical acquisition; the boundary guard holds
`src/` to those two. This ADR names the production adapter as the **third and last** site, held by a
counterpart assertion to exactly one construction around an injected transport and a caller-supplied
credential, a one-attempt policy and a zero-interval pacer — no transport, opener, credential source or
environment read may appear at it. A fourth site is a guard failure.

**Request identity and the plan digest are unchanged.** The compiled plan already binds
`(dataset, window, page_offset, page_limit)` into every request ordinal, claim, record and locator
entry; this form transmits exactly those coordinates. No plan field, digest input or locator field is
added or reinterpreted, and every earlier synthetic artifact validates as before.

**Response completeness and the terminal page.** A response is the bytes the vendor returned for one
compiled coordinate, published byte for byte; the adapter never judges completeness. A window's second
page is the plan's completeness probe: **header-only means the first page was complete**. A final page at
the limit is `DELIVERY_TRUNCATED` at the build (ADR-0040). **A non-empty second page of a one-session
cross-section is explicitly unsupported for production** until the vendor documents a stable order across
offsets or the plan is amended to request one (`PSR-SHD-133`): the rows of such a page cannot be shown to
be the rows the first page did not return.

## 4. Compatibility requirements

1. `SharadarRequest`, `build_query_parameters`, `build_request_url`, the accepted allowlist and forbidden
   set, and the qualification composition are byte-for-byte unchanged in behaviour; a test holds the
   accepted form's serialization to its literal parameter order.
2. The client's `fetch` and the new `fetch_cross_section` run the same loop; a change to one is a change
   to both.
3. The adapter transmits nothing outside the compiled request: no arbitrary URL, host, filter, header or
   credential destination exists in its shape.
4. Earlier synthetic Bronze artifacts, locators and build inputs validate unchanged.

## 5. Effectiveness and execution gates

- **Effectiveness**: this amendment is in force only on the independently reviewed merge of the pull
  request introducing it, together with the offline adapter beside it. Until then both are proposed.
- **Execution — refused and unresolved**, each a separate written authorization and none opened here:
  - **`from`/`to` inclusivity is an assumption** (`PSR-SHD-129`); a first bounded ingestion's calendar
    completeness checks would expose a systematic off-by-one, and no live request may be made to settle
    it in advance.
  - **Multi-page one-session cross-sections are unsupported** (`PSR-SHD-133`); a build that meets one
    must refuse it, which is a build-side rule this ADR names and a later change implements.
  - Error, throttling and truncation behaviour are **undocumented** (`PSR-SHD-132`); the adapter's
    classification is by HTTP status only and makes one attempt.
  - The task-side spent-identity source, the production image and entry point, R-3/R-5 verification,
    Terraform plan/apply, image publication, task launch and the first bounded ingestion stay
    **NOT AUTHORIZED / NOT RUN**.
- **Scope**: nothing here amends ADR-0009's transport, credential or redaction decisions, ADR-0019's
  write-only publication, ADR-0035's design, ADR-0036's grants, or ADR-0037/0038/0040's layouts.

## 6. Rejected alternatives

- **Make `ticker` optional on `SharadarRequest`.** Weakens validation the qualification path relies on
  and lets a qualification probe silently become a cross-section.
- **Add a `date` parameter.** The vendor documents none; a one-day window already expresses a session.
- **Send `sort` for a stable page order.** Forbidden by ADR-0009 because it changes the byte stream; the
  undocumented-order case is refused instead.
- **Translate offsets into a cursor.** The vendor documents offset pagination; no translation is needed
  and none is invented.
- **Use the tickers table's `from`/`to`.** They bound `lastpricedate` and would narrow the snapshot.

G2 OPEN; CONTROL DEFERRED; Phase 3 NOT COMPLETE; live trading HARD-DISABLED.
