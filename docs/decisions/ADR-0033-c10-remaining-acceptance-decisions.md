# ADR-0033 — The remaining C10 acceptance decisions: mobile summary, performance budgets, visual coverage and the manual screen-reader protocol

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0033 is proposed and carries no authority,
and so are the deltas it makes to `ui-ux-specification.md` in the same pull request. That is a
statement about the present, it will remain true of these days after any later merge, and it is not
to be rewritten as though this decision had authority before it was accepted. On merge, this ADR
becomes **ACCEPTED / IN FORCE** as **acceptance criteria, measurement conditions, coverage rules and
an assessment protocol** — and nothing else.

**The acceptance event is exact:** the independent review and merge, into `main`, of the pull
request introducing this ADR. No merge SHA and no merge timestamp is predicted here; those are
repository state, recorded after the fact if they are recorded at all.

**Acceptance of this ADR establishes what "done" means for four outstanding C10 items. It does not
make any of them done.** Accepting a budget is not meeting it; accepting a coverage inventory is not
capturing it; accepting an assessment protocol is not running it; accepting a mobile behaviour is
not building it. Each of those is a later, separately authorized implementation or assessment cycle,
and **C10's §15 assessment stays at one satisfied criterion of four until evidence under accepted
authority says otherwise**.

**Date:** 2026-09-10
**Supersedes:** nothing
**Superseded by:** —
**Amends:** [`docs/cockpit/ui-ux-specification.md`](../cockpit/ui-ux-specification.md) at **§12**
(one clarifying subsection on the mobile row) and **§15** (four subsections giving the future
criteria their acceptance definitions). **It amends no other section of that document, and no other
document.** It does **not** amend, supersede or edit ADR-0026, ADR-0027, ADR-0028, ADR-0029,
ADR-0030, ADR-0031 or ADR-0032, each of which remains as it stands; it edits no read-model contract,
no traceability-matrix row and no accepted acceptance criterion U1–U20.
**Relates to:** [ADR-0027](ADR-0027-cockpit-and-feedback-architecture-and-governance.md),
[ADR-0031](ADR-0031-reference-owning-area-navigation.md),
[`docs/cockpit/c10-acceptance-record.md`](../cockpit/c10-acceptance-record.md)

**Nothing was run to produce this decision.** No AWS, STS, SSO, IAM, Secrets Manager or S3 call; no
Terraform command of any kind; no Terraform state, backend configuration, `.tfvars` or `.terraform/`
read; no `.runtime/` inspection; no provider request; no credential access; no Run A retry, Run B or
combined assessment; no P1–P9 execution; no backtest; no model calibration; and no broker, LEAN or
IBKR activity. **No Blueprint PDF was opened or edited.** No dependency was installed, no package
manifest was changed, **no browser suite was launched, no screenshot baseline was created or
regenerated, no performance measurement was taken, no CI configuration was touched, and no user
interface was changed**. This decision is authored from tracked repository authority and from the
retained C10 and PR #87 measurement evidence, read in place and copied nowhere.

**No human accessibility assessment occurred**, and none is claimed anywhere below. **No alpha is
claimed anywhere in this decision, and no number in it is a trading rule.**

---

## 1. Context — four things the accepted text leaves undecided

**C10 merged with one of its four §15 criteria satisfied, and the acceptance record says exactly why
the other three are not.** Each of the three, and one §12 requirement, waits on a decision that the
accepted text does not take. This ADR takes them.

```text
1  ui-ux-specification.md 12, the 390 x 844 row
       "executive summary only -- tier 1, Attention Required and search"
   c10-acceptance-record.md 7.2 -- the mobile Executive Overview renders the FULL stacked page;
       the accepted text does not settle whether the rest is OMITTED or DEFERRED, and no route
       owns What Changed or the tier-2 tiles, so omission would remove specified executive
       information with no navigation to it.                     DISPOSITION: NOT SATISFIED

2  ui-ux-specification.md 15 -- "performance targets ... set as targets for the implementation
       cycle to measure"
   c10-acceptance-record.md 7.3 -- measured on a development server AND a production build,
       each with its conditions; "no numeric performance budget exists anywhere in tracked
       authority, so none is asserted"; first contentful paint NOT OBTAINED on the production
       run.                                                       DISPOSITION: PARTIAL

3  ui-ux-specification.md 15 -- "a stable baseline per route and per state"
   c10-acceptance-record.md 7.4 -- a committed baseline of NINE images exists, compared at zero
       tolerance; it covers a REPRESENTATIVE SUBSET, not all thirty routes in every state.
                                                                  DISPOSITION: PARTIAL

4  ui-ux-specification.md 11 and 15 -- "manual keyboard and screen-reader passes, because an
       automated pass is not an accessible interface"
   c10-acceptance-record.md 7.1 -- "NOT_ASSESSED. No screen reader was run by the author, and
       none was available to the independent review either."   DISPOSITION: NOT ASSESSED
```

**These are decisions, not defects.** The C10 cycle and its independent review were right not to take
them: inventing a mobile product design, a performance threshold, a coverage rule or an assessment
result inside an implementation cycle would have manufactured authority nobody had granted. The
record left each one named, bounded and open, which is what this ADR now closes — as a decision,
under review, and nothing more.

### 1.1 What is preserved, verbatim

**Every accepted requirement stays in force unless this ADR names it and says why it moves.** In
particular:

| Preserved | Where it stands |
|---|---|
| **§12's six reference viewports and their per-row requirements** | unchanged. The 1920 and 1440 first-viewport rules, the 1280 navigation rule, the 1024 rail, the 768 single column and the 390 summary all stand; §12.1 below **clarifies** the 390 row and **narrows nothing** in it |
| **§12's tail — "Operator tables are reachable and explicitly narrow"** | unchanged, and load-bearing: it is the clause that shows §12 never intended mobile to *lose* content |
| **§2 and §6 — the five ten-second answers, three tiers, Attention Required** | unchanged. The summary content is the accepted summary content; this ADR adds no tile and drops none |
| **§5 — environment, source and freshness on every route** | unchanged, and required at the mobile summary exactly as elsewhere |
| **§7 and U17 — an unavailable endpoint is not a change** | unchanged. The What Changed tile keeps reporting a state instead of a delta at every width |
| **U1–U20** | unchanged, every one. This ADR adds acceptance definitions beside them; it edits none |
| **§15 — "a diff is a review item, not an auto-accept"** | unchanged, and restated as a rule with teeth in §4 |
| **the nine committed zero-tolerance comparisons** | preserved exactly: `threshold: 0`, `maxDiffPixels: 0`, `maxDiffPixelRatio: 0`. No different policy is applied to them; **a different tolerance for any image would be a separate proposal, and none is made** |
| **the disposition vocabulary of the acceptance record** | unchanged — `IMPLEMENTED`, `ACCEPTED_UNAVAILABLE`, `PARTIAL`, `BLOCKED_CONTRACT`, `NOT_ASSESSED`, with `NOT_ASSESSED` never reported as a pass |

---

## 2. Decision M — the mobile Executive Overview is a summary with everything else deferred, not omitted

**One behaviour, and not a menu.** At the mobile width the Executive Overview renders the accepted
summary first, and **every other section of the page is deferred behind a labelled, accessible
disclosure on the same page** — never omitted, never moved to an invented route, and never hidden
in a way that could be mistaken for missing data.

### M1 — the breakpoint, and where it applies

| | |
|---|---|
| **breakpoint** | the summary behaviour applies when the **viewport width is below 640 CSS pixels** — the `sm` breakpoint the Executive Overview already lays its tiers out against (`grid-cols-1 sm:grid-cols-2`). **It is grounded in the existing viewport scheme**: 390 × 844 is below it; 768 × 1024, the tablet-portrait row, is above it and keeps §12's *"single-column stacking"* with **no** disclosure |
| **routes** | **`/` only** — the Executive Overview, area 1. No other route acquires a summary behaviour: `/attention` is the full ranked list's own route, and operator tables stay *"reachable and explicitly narrow"* on their own routes exactly as §12 says |
| **modes** | **both.** Executive and Operator modes both render the summary below the breakpoint; the Operator mode's *Response evidence* section is one more deferred section (M3) |
| **scenarios** | **both.** `project` and `demo` provenance both render the summary; the disclosures carry the same provenance badges the sections carry today |
| **implementation freedom** | how the breakpoint is detected — a CSS media query, a `matchMedia` listener, a container query — is an implementation choice, provided the **rendered behaviour** below is met and the same DOM content exists at every width |

### M2 — what is visible initially

**The accepted summary contents, in the accepted order, and nothing added.** From §12 —
*"tier 1, Attention Required and search"* — and §6's tiering:

```text
INITIALLY VISIBLE, in document order
  the shell          skip links · context bar (environment, source, freshness) · page provenance
                     banner · Search / command-palette trigger · mode switch
  the page header    h1, summary sentence, PAGE-LEVEL STATE BADGE (COMPLETE / PARTIAL / ERROR)
  TIER 1             the six answer tiles, exactly as today, stacked one per row:
                     tile-strategy-capital · answer-performance · answer-risk · answer-health ·
                     answer-changed · answer-attention -- each with its provenance, its
                     availability and its link to the owning area
  ATTENTION REQUIRED the attention panel with its current mobile limit of two ranked items, each
                     showing what happened, why it matters, impact, evidence and the permitted
                     governance action -- and its "open the full list" link to /attention
  (project scenario, Executive mode only)
  "Why these tiles are empty" -- the explanation of the unavailable state. AN EXPLANATION OF AN
                     UNAVAILABLE STATE IS NEVER DEFERRED, because deferring it is how an absence
                     starts to read as an omission
```

**Search is the shell's search control**, present on every route; it is not a page section and it is
not moved.

### M3 — where every deferred section remains accessible

**Every section that exists on the page today keeps existing on the page, in the same document order,
behind a disclosure.** No section moves to another route, because **no route owns What Changed or
the tier-2 supporting-context tiles**, and inventing one is exactly what §7.2 of the acceptance
record declined to do. The content-to-location table an implementer must account for:

| Section today (test id or heading) | At ≥ 640 px | At < 640 px | Owning route, if one exists |
|---|---|---|---|
| shell: `skip-to-main`, `context-bar`, `page-provenance-banner`, search trigger, mode switch | unchanged | **VISIBLE** | every route |
| page header: `h1`, summary, `page-state` badge | unchanged | **VISIBLE** | — |
| tier 1: `tile-strategy-capital` | unchanged | **VISIBLE** | `/governance/qualification` |
| tier 1: `answer-performance` | unchanged | **VISIBLE** | `/portfolio/performance` |
| tier 1: `answer-risk` | unchanged | **VISIBLE** | `/risk` |
| tier 1: `answer-health` | unchanged | **VISIBLE** | `/system/operations` |
| tier 1: `answer-changed` — the tile, its state or delta count, its baseline footer | unchanged | **VISIBLE** | `/governance/audit` — the tile's existing link; **the audit trail does not own What Changed** |
| tier 1: `answer-attention` | unchanged | **VISIBLE** | `/attention` |
| `attention-panel`, two ranked items | unchanged | **VISIBLE** | `/attention` |
| `what-changed-panel` — the item list, endpoints, evidence, and the `changes` variant selector in `demo` | unchanged | **DEFERRED — disclosure `What changed — details`** | **none** |
| `performance-overview` — chart, `period-selector`, `granularity-selector`, `series-table-disclosure` | unchanged | **DEFERRED — disclosure `Performance overview`** | `/portfolio/performance` |
| tier 2: `tile-open-gates` | unchanged | **DEFERRED — disclosure `Supporting context`** | `/governance/qualification` |
| tier 2: `Broker-reported equity` metric tile | unchanged | **DEFERRED — `Supporting context`** | **none** — an observed reconciliation fact; `/execution/reconciliation` does not own it |
| tier 2: `Drawdown` metric tile | unchanged | **DEFERRED — `Supporting context`** | `/portfolio/performance` |
| tier 2: `Permitted open risk` metric tile | unchanged | **DEFERRED — `Supporting context`** | `/risk` |
| tier 2: `tile-exposure` | unchanged | **DEFERRED — `Supporting context`** | `/portfolio/positions` |
| tier 2: `tile-last-runs` — regime, last decision, last scout run | unchanged | **DEFERRED — `Supporting context`** | `/market/regime` for the regime; **none** for the two last-run records |
| Operator mode: `Response evidence` (`operator-evidence`) | unchanged | **DEFERRED — disclosure `Response evidence`**, Operator mode only | — |
| Executive mode, `project` scenario: `Why these tiles are empty` | unchanged | **VISIBLE** | — |

**Three disclosures in Executive mode, four in Operator mode, and every existing section is in the
table.** A section added to the Executive Overview by a later cycle **must be added to this table by
the cycle that adds it**, with a stated location; a governance test holds the table to the page's
section inventory so a section cannot silently fall out of it.

**Nothing is relabelled and nothing is invented.** No reference kind changes, no *view evidence*
wording appears on a disclosure, no area control is added (ADR-0031), and no destination is created.
The owning-route column above records where an owning route **already** exists; it authorizes no
navigation change.

### M4 — the critical exceptions that stay visible without expansion

**A collapsed section may hide detail. It may never hide that something is wrong.**

| Always visible at the mobile width | Why |
|---|---|
| the **page-level state badge** — `PARTIAL` or `ERROR` — in the header | U6: a failing widget anywhere on the page, including inside a collapsed section, is reported at page level |
| the **freshness indicator**, including `STALE` | §5, U2: freshness is visible on every route at all times |
| the **`answer-health` tile** — system health and open incidents, or its availability state | this is the *"Is anything wrong?"* answer, and it is tier 1 |
| the **two highest-ranked attention items** | §6: *"an attention list below the fold is a list nobody reads"* — and a list behind a disclosure is one nobody expands |
| the **What Changed tile's state** — a delta count, `EMPTY_VERIFIED`, or the unavailable-endpoint state (U17) | the tile is tier 1 and answers *"What changed?"*; only the itemized detail is deferred |
| **every tier-1 tile's own availability badge** | U4/U5: an unavailable state renders distinctly and never as a value |
| **each disclosure's aggregate availability badge** (M5) | so a degraded tier-2 tile or a degraded What Changed panel is visible on the collapsed control itself |

### M5 — disclosure labels, keyboard operation, focus and expanded-state semantics

| | |
|---|---|
| **control** | a native `<details>`/`<summary>` element, which the application already uses for evidence and chart-table disclosures, **or** a `<button aria-expanded aria-controls>` pattern. Either is acceptable; **the semantics below are required whichever is chosen** |
| **labels** | fixed text, and never a number: `What changed — details`, `Performance overview`, `Supporting context`, `Response evidence`. The **section's existing `h2` is the summary's visible text**, so heading navigation still lists every section whether it is collapsed or not |
| **expanded state** | exposed to assistive technology as expanded/collapsed (`open` on `<details>`, or `aria-expanded="true|false"`), so a screen reader hears *collapsed* rather than silence |
| **default state** | **collapsed** on page load below the breakpoint |
| **keyboard** | the control is in the tab order in document order; `Enter` and `Space` toggle it; **focus stays on the control after a toggle** in both directions, so a reader who collapses a section is not thrown to the top of the page. No focus trap, no focus move into the revealed content |
| **aggregate availability badge** | when any widget inside a collapsed section is in a state other than `AVAILABLE`, the summary carries the section's **worst** availability state using the existing `AvailabilityBadge` — glyph and label, never colour alone (U11), never a number, never a skeleton. `ERROR` outranks `PARTIAL` outranks `STALE` outranks every other non-`AVAILABLE` state; the exact order is an implementation detail provided `ERROR` is never outranked |
| **provenance** | the summary carries the section's provenance badge exactly as the section header does today, so a collapsed synthetic section is still labelled `SYNTHETIC` (U3) |
| **no data on the control** | a disclosure control **never** carries a metric value, a delta, a count of changes or a plausible placeholder. It carries a label, a provenance badge and, when applicable, an availability badge — and nothing else |

### M6 — loading, empty, unavailable and errored content behind a disclosure

| Content state | Collapsed control shows | Expanded section shows |
|---|---|---|
| **loading** | the label and provenance; **no skeleton and no badge** — a pending read is not an availability state | the section's existing shape-only skeletons (U7, §9.3) |
| **`EMPTY_VERIFIED`** | the label, provenance and the `EMPTY_VERIFIED` badge | the section's existing empty rendering with its as-of |
| **`NOT_YET_AVAILABLE` / `NOT_IMPLEMENTED` / `NOT_AUTHORIZED`** | the label, provenance and that badge | the existing `UnavailableBody` with its named dependency |
| **`STALE` / `PARTIAL`** | the label, provenance and that badge | the existing rendering, age and missing extent stated |
| **`ERROR`** | the label, provenance and the `ERROR` badge — **and the page-level badge already reads `PARTIAL`** (U6) | the existing error rendering with its closed reason code and no fabricated payload |

**A collapsed section is never how a defect is made responsive.** A widget that overflows, clips or
misrenders at 390 × 844 fails U14 and §12 whether or not it is behind a disclosure, and the U14
sweep (`clippedBeyondViewport`) runs with every disclosure **expanded** as well as collapsed.

### M7 — resize, orientation and persistence

| | |
|---|---|
| **crossing the breakpoint upward** | every section renders as it does today, fully, with **no** disclosure control; nothing the reader expanded is lost, because the same DOM content is present |
| **crossing the breakpoint downward** | the disclosures appear; **a section the reader expanded during this page instance stays expanded**, so rotating a phone to landscape and back does not collapse what was open |
| **persistence** | expansion state lives **for the page instance only**. It is **not** written to the URL, because a disclosure is a presentation preference and not view scope — §8's saved context covers *"filters, ranges, mode and scoping"*, and a disclosure changes none of them. It is **not** written to storage. A navigation away and back, or a reload, returns to the default collapsed state |
| **mode switch on the same page** | preserves expansion state (U15: a mode switch does not reset the view); the *Response evidence* disclosure appears collapsed when Operator mode is entered |

### M8 — the tests that establish it, and the confusion they must not make

**A test that finds a section absent has found a defect or a collapsed disclosure, and it must know
which.** The tests a later implementation cycle owes:

| Test obligation | What it establishes |
|---|---|
| **M8.1 — the summary set** | at 390 × 844 the initially visible sections are exactly the M2 set, in document order, and every other section's disclosure control is present and collapsed |
| **M8.2 — presence, not absence** | for **each** deferred section: the control is collapsed (`open` absent / `aria-expanded="false"`), activating it by keyboard reveals the section's **existing** test ids (`what-changed-panel`, `performance-overview`, `tile-open-gates`, `tile-exposure`, `tile-last-runs`, `operator-evidence`), and the revealed content is byte-for-byte the content the desktop layout renders for the same scope — **hidden content is never read as missing data** |
| **M8.3 — the exceptions** | with a fixture that degrades one tier-2 tile (the demo scenario already does: the permitted-risk tile is unavailable), the collapsed `Supporting context` control carries an availability badge and the page-level badge reads `PARTIAL` |
| **M8.4 — no value on a control** | no disclosure control contains a digit, a currency symbol, a percent sign or an `R` figure |
| **M8.5 — focus** | after `Enter` on a control, `document.activeElement` is still the control; after `Escape` nothing on the page changes |
| **M8.6 — above the breakpoint** | at 768 × 1024 and at every wider reference viewport, **no** disclosure control renders and every section is visible — the existing sweeps continue to see the full page |
| **M8.7 — U14, expanded** | `clippedBeyondViewport` and the overflow check pass at 390 × 844 with every disclosure expanded |
| **M8.8 — provenance and freshness** | the U2/U3 assertions hold at 390 × 844 in both the collapsed and expanded states |

**None of these tests exists, and this ADR writes none.** They are the acceptance obligation of the
implementation cycle that builds M1–M7.

### M9 — what M does not do

It does **not** change the desktop or tablet layouts; it does **not** add, remove or reorder a tile;
it does **not** create a route, an area control or a reference kind; it does **not** move What
Changed to the Audit Trail or anywhere else; it does **not** persist anything; and it does **not**
build anything. **Decision M is the definition the §12 mobile row was missing, and its disposition
in the acceptance record stays `NOT SATISFIED` until an implementation meets M8.**

---

## 3. Decision PB — measurable performance budgets, and the conditions under which they mean anything

### 3.1 What was measured, what was not, and what is proposed — kept apart

**Measured, production build** (`next start`, minified and precompiled), `desktop-1440`, one
Playwright worker, local loopback, local fixture adapter, one machine, one run each, retained in the
PR #87 review evidence and reported in the acceptance record §7.3:

```text
route                        first answer   DOMContentLoaded   load    transferred
/                              618 ms            166 ms        329 ms   531 KB
/portfolio/trades              462 ms             38 ms        186 ms   418 KB
/portfolio/performance         384 ms             39 ms        170 ms   530 KB
/governance/qualification      269 ms             32 ms        137 ms   399 KB
/system/alerts                 311 ms             32 ms        178 ms   537 KB
interactions                 palette open 51 ms   ·   Executive -> Operator 211 ms
first contentful paint       NOT OBTAINED -- the paint entry was absent on every route
```

**Measured, development server** (`next dev`, compiled on demand, unminified), three viewports,
several runs retained across the author's and the review's evidence: first answer **569 to 2 392 ms**
across runs and viewports, transferred **1.4 to 1.8 MB**, first contentful paint **168 to 656 ms**
where present. **These describe a development server and are not comparable with a production
figure in either direction**; the acceptance record withdrew the claim that they bound one.

**Not obtained, and stated as such:** first contentful paint on the production run — the paint entry
was absent when the measurement script read `performance.getEntriesByType("paint")`. **The reason is
not established** by any retained evidence; a likely mechanism is that the entry had not been
recorded, or had been dropped from the buffer, by the time the script ran after hydration, but that
is a hypothesis and not a finding. **A missing entry is `NOT OBTAINED`. It is never zero, never a
pass, and never excluded from the denominator** (PB6).

**Every number in §3.2 is a proposed engineering target.** None is derived from a service-level
requirement, because none exists; none is a field measurement, because no Cockpit is deployed; and
none was chosen to make the figures above pass — the production figures pass most of them with room,
and the development figures fail several of them, which is what a budget that constrains anything
looks like.

### 3.2 The budgets — PB1 to PB5

**Units are milliseconds unless stated; every budget names its measurement (§3.3), its condition
(§3.4) and its aggregation (§3.5).**

| Id | Event measured | Budget, Condition L | Rationale |
|---|---|---|---|
| **PB1** | **first answer** — navigation start to **read-model readiness**: the first client read resolved and the freshness indicator rendered | **p50 ≤ 1 000 ms · no sample > 1 500 ms** | the reader's one-second perception boundary for *"the page is answering"*; production measured 269–618 ms, so the budget leaves headroom for a real read-model boundary without admitting the 1.1–2.4 s development figures |
| **PB2** | **first contentful paint** — the `first-contentful-paint` performance entry | **p50 ≤ 800 ms · no sample > 1 200 ms** — **evaluable only when obtained** | the paint precedes the answer; the budget is below PB1 by construction. **It cannot be evaluated today**: the production run obtained no entry, and the measurement must be corrected (PB6) before this budget reports anything but `NOT OBTAINED` |
| **PB3** | **interaction — command palette** — `Ctrl/Cmd+K` keypress to the palette visible | **p50 ≤ 100 ms · no sample > 200 ms** | the accepted keyboard-first design (§10) is only real if the palette feels instantaneous; 100 ms is the response boundary below which an interaction reads as direct manipulation. Production measured 51 ms |
| **PB4** | **interaction — mode switch** — Operator radio activation to the response-evidence section rendered | **p50 ≤ 300 ms · no sample > 500 ms** | a mode switch re-renders every panel in evidence mode; 300 ms is the boundary below which the switch reads as one step rather than a reload. Production measured 211 ms |
| **PB5** | **transferred bytes** — `transferSize` summed over the navigation's resource entries | **≤ 750 KB per route, compressed** | bounds bundle growth as read-model and chart code lands; production measured 399–537 KB. **Not a timing** and not condition-sensitive, so it is evaluated once per route per run |

**Bounded query time — the third target §15 names — is deliberately not given a number here.** Every
read today resolves in-process from the fixture adapter, so a query-time budget would measure a
function call and describe nothing about a read API that does not exist. **PB-Q is recorded as
`DEFERRED — requires a read-model boundary`**, and the cycle that introduces a real read boundary
owes the number with it.

### 3.3 Start and end marks

| Measurement | Start | End |
|---|---|---|
| **PB1 first answer** | `PerformanceNavigationTiming.startTime` (0) for the navigation | the instant `freshness-indicator` becomes visible — the existing `waitForHydration` mark, which is the first **resolved** client read and therefore **read-model readiness** rather than paint. Measured with `performance.now()` inside the page at the moment the indicator is observed, **not** with the test runner's wall clock, so runner latency is excluded |
| **PB2 first contentful paint** | navigation start | the `first-contentful-paint` entry's `startTime`, captured by a **`PerformanceObserver` registered before navigation with `buffered: true`** rather than read after the fact (PB6) |
| **PB3 palette** | the `keydown` dispatched for `Ctrl/Cmd+K` | `command-palette` visible |
| **PB4 mode switch** | the `click` on the Operator radio | the `Response evidence` heading visible |
| **PB5 transferred** | — | the sum of `transferSize` over `resource` entries at PB1's end mark |

**A measurement whose end mark is never reached is a failed navigation or interaction** (PB6).

### 3.4 Conditions — L, M and F, and which budgets apply where

| Condition | Definition | Budgets that apply |
|---|---|---|
| **L — local production** | `next build` then `next start`, on the suite's port, on loopback; **one** Playwright worker; Playwright's `Desktop Chrome` device; **1440 × 900**; **no** CPU or network throttling; the local fixture adapter; the machine, OS, Node, Next and Playwright versions **recorded in the evidence file** | **PB1–PB5** as stated |
| **M — local production, mobile** | Condition L with **390 × 844** and a **4× CPU slowdown** applied through the Chrome DevTools Protocol (`Emulation.setCPUThrottlingRate`, rate 4); no network throttling, because the transport is loopback and a synthetic network profile would describe the profile rather than the application | **PB1–PB4 at 2× the Condition L figures**; PB5 unchanged. **Proposed and unmeasured**: no retained run used throttling, so these figures have no observed sample behind them and are recorded as targets only |
| **F — field / deployed** | a deployed Cockpit reached over a real network by a real device | **no budget is set.** No Cockpit is deployed, none is authorized, and **local timings do not establish production service performance**. The cycle that deploys owes Condition F budgets with the deployment |

**The development server is not a condition.** `next dev` may still be measured and recorded — the
retained evidence is useful as a paired sample — but **no budget is evaluated against a development
server**, because a development server's compilation, bundling and caching are not the application's.

### 3.5 Cold and warm, samples, aggregation and variability

| | |
|---|---|
| **warm-up** | after `next start`, one navigation to every measured route is made and **discarded**, so no sample includes the server's first-request compilation or cache fill |
| **cold** | every budgeted sample is taken in a **fresh browser context** — a cold in-memory cache and no service-worker state. **Budgets apply to cold samples** |
| **warm** | one additional same-context second navigation per route is recorded as a warm sample **for information**; no budget applies to it |
| **samples** | **five** cold samples per route per condition, taken as five independent navigations |
| **aggregation** | the **median** of the five is compared with the p50 budget; **every** sample is compared with the ceiling. Both must hold. With five samples a p90 is the maximum, which is why the ceiling is stated as *no sample above* rather than as a percentile |
| **permitted variability** | none is added to the budget: the ceiling is the variability allowance. A route whose five samples straddle the ceiling has failed the ceiling, and the run is reported as it happened |
| **repeat runs** | a budget failure may be re-run **once**, with both runs retained and both reported. A second failure is a failure |

### 3.6 Failed navigations and missing measurements — PB6

```text
a navigation that does not reach the PB1 end mark within the suite timeout
    -> FAILED NAVIGATION -- reported as a failure of PB1 for that route; NOT a missing sample,
       NOT excluded, NOT retried silently
a performance entry that is absent (first contentful paint today)
    -> NOT OBTAINED -- the budget it feeds is reported NOT OBTAINED for that route and condition;
       NEVER zero, NEVER passing, NEVER dropped from the denominator
an interaction whose end mark is never observed
    -> FAILED INTERACTION -- a failure of its budget
a sample of exactly 0 ms, or a negative one
    -> INVALID SAMPLE -- reported, and the run is not accepted until the measurement is corrected
```

**The evidence file records every sample, not a summary**, with the server description, the
condition, the versions and the git tree it was taken from. **PB2's measurement is corrected before
PB2 is evaluated**: the observer is registered before navigation with `buffered: true`, and a run in
which the entry is still absent reports `NOT OBTAINED` and states so in the acceptance record.

### 3.7 Routes and scenarios, and why

| Route | Why it is measured |
|---|---|
| `/` | the landing page and the U1 surface; the heaviest composition on the site (six tiles, two panels, a chart, six tier-2 tiles) |
| `/portfolio/trades` | the densest table |
| `/portfolio/performance` | the chart-heavy route, and the Recharts bundle |
| `/governance/qualification` | the `REPOSITORY_TRACKED` governance screen — real facts, no fixture book |
| `/system/alerts` | a list route with filters |
| **`/strategy/performance`** — **added** | the module-card route the review found rendering several regions per version and per family; its render cost is the one most likely to grow |
| **`/portfolio/trades/[tradeId]`** — **added**, one fixed fixture identifier | the deep destination that loads the price-chart library; a detail route is a different bundle from a ledger |

**Scenario:** `demo`, because it populates every panel and therefore measures the render rather than
the unavailable state; `project` is measured for `/` only, as the second state of the same route.
**Both** are recorded; **budgets are evaluated against `demo`**, the heavier of the two.

### 3.8 What acceptance of PB establishes — and what it does not

**Acceptance establishes the budgets. It establishes no compliance.** No retained run satisfies the
sampling protocol (five cold samples per route, warm-up discarded, versions recorded), no retained run
obtained PB2, no Condition M run exists, and Condition F has no budget. **The §15 performance row
stays `PARTIAL`** until a run under §3.3–§3.7 is retained and read into the acceptance record — and
**this documentation cycle launches no run to re-create evidence that already exists**.

---

## 4. Decision VC — per-route-and-state visual regression coverage, as an inventory

### 4.1 The requirement, and the interpretation this ADR proposes

§15 asks for *"a fixed synthetic fixture set, a fixed viewport list, deterministic rendering, and a
stable baseline **per route and per state**"*. Three words in that clause are undefined — *route*,
*state*, *fixed viewport list* — and the nine-image baseline is `PARTIAL` because nobody had defined
them. **This ADR proposes the definitions, marks each as an interpretation requiring acceptance, and
neither silently requires nor silently waives a Cartesian product.**

| Id | Term | Proposed interpretation |
|---|---|---|
| **VC-I1** | **route** | every entry of the typed navigation registry (`NAV_ROUTES`, thirty today) **and** every deep destination (`DEEP_DESTINATIONS`, two today), the latter captured at **one fixed representative fixture identifier** recorded in the inventory, plus **one absent identifier** for the ADR-0030 unavailable-target rendering |
| **VC-I2** | **state** | a rendering the accepted scope selectors can reproduce **deterministically from a URL**: the **scenario** axis (`project` — producers absent; `demo` — populated), the **mode** axis (`executive`, `operator`), and any **declared variant** a route exposes (today: the What Changed `changes` variants on `/`, in `demo`). **Transient loading is not a route state**: it is covered by U7's shape-only rule at component level and by the skeleton on the state-reference screen. **Route-level `ERROR` is not reproducible from a URL today** and is covered by the eleven-state reference screen (`/foundation/states`) until a deterministic error selector exists — **and adding one is a later cycle's work, not this ADR's** |
| **VC-I3** | **fixed viewport list** | **the three original widths — 1440 × 900, 1024 × 768, 390 × 844 — for every route**, which is the fixed list §15's own commentary and the suite have always used; **all six reference viewports for `/`**, because §12 states a distinct per-viewport requirement for the Executive Overview on four of its six rows; and **390 × 844 additionally for the M-decision expanded state** once M is implemented |
| **VC-I4** | **inapplicable** | a combination is legitimately inapplicable **only** under a rule listed in §4.3, cited by rule id in the inventory. **An inapplicability without a cited rule is a gap**, and a gap is reported as `PARTIAL` coverage rather than as a complete baseline |

**The alternative not taken:** a full product — 32 routes × 4 states × 6 viewports plus variants,
roughly 800 images. It is not required by §15's words, it would multiply the tracked baseline to
well over 100 MB for widths whose structural requirements the six-viewport sweep already checks, and
it would make every deliberate design change a review of hundreds of diffs. **It is not silently
waived either**: VC-I3 is a proposed interpretation, stated here, and accepting this ADR accepts it.

### 4.2 The inventory

**Stable identifiers.** A snapshot is named `VC-<route-id>-<scenario>-<mode>[-<variant>]` at
`<project-name>`, and the file follows the existing template
`visual-baseline/{projectName}/{arg}-{platform}.png`. Route ids are the registry `href` with `/`
replaced by `-` and the leading dash dropped (`/` → `root`; `/portfolio/trades/[tradeId]` →
`portfolio-trades-detail`).

| Route id | Route | Scenario axis | Mode axis | Variants | Viewports | Nominal snapshots |
|---|---|---|---|---|---|---|
| `root` | `/` | 2 | 2 | `changes` ∈ {`valid`, `none`, `no-baseline`, `degraded`} in `demo`/`executive` → +4 | **6** (VC-I3) | (4 + 4) × 6 = **48**, plus **2** at 390 for M expanded (`demo`, `project`) once M exists = **50** |
| `attention` | `/attention` | 2 | 2 | — | 3 | **12** |
| `portfolio-performance` | `/portfolio/performance` | 2 | 2 | — | 3 | **12** |
| `portfolio-positions` | `/portfolio/positions` | 2 | 2 | — | 3 | **12** |
| `portfolio-trades` | `/portfolio/trades` | 2 | 2 | — | 3 | **12** |
| `portfolio-trades-detail` | `/portfolio/trades/[tradeId]` | 2 — `demo` at the fixed identifier; `project`/absent identifier renders the unavailable target (VC-I1) | 2 | — | 3 | **12** |
| `strategy-performance` | `/strategy/performance` | 2 | 2 | — | 3 | **12** |
| `strategy-health` | `/strategy/health` | 2 | 2 | — | 3 | **12** |
| `strategy-champion-challenger` | `/strategy/champion-challenger` | 2 | 2 | — | 3 | **12** |
| `strategy-versions` | `/strategy/versions` | 2 | 2 | — | 3 | **12** |
| `signals-funnel` | `/signals/funnel` | 2 | 2 | — | 3 | **12** |
| `signals-candidates-detail` | `/signals/candidates/[candidateId]` | 2 — as for the trade detail | 2 | — | 3 | **12** |
| `signals-missed` | `/signals/missed` | 2 | 2 | — | 3 | **12** |
| `risk` | `/risk` | 2 | 2 | — | 3 | **12** |
| `risk-short-side` | `/risk/short-side` | 2 | 2 | — | 3 | **12** |
| `market-regime` | `/market/regime` | 2 | 2 | — | 3 | **12** |
| `execution-quality` | `/execution/quality` | 2 | 2 | — | 3 | **12** |
| `execution-reconciliation` | `/execution/reconciliation` | 2 | 2 | — | 3 | **12** |
| `research-runs` | `/research/runs` | 2 | 2 | — | 3 | **12** |
| `research-queue` | `/research/queue` | 2 | 2 | — | 3 | **12** |
| `research-hypotheses` | `/research/hypotheses` | 2 | 2 | — | 3 | **12** |
| `research-feedback` | `/research/feedback` | 2 | 2 | — | 3 | **12** |
| `research-ai-contribution` | `/research/ai-contribution` | 2 | 2 | — | 3 | **12** |
| `governance-packets` | `/governance/packets` | 2 | 2 | — | 3 | **12** |
| `governance-qualification` | `/governance/qualification` | **1 — VC-R1**: `REPOSITORY_TRACKED` only, identical under both scenarios | 2 | — | 3 | **6** |
| `governance-maturity` | `/governance/maturity` | 2 | 2 | — | 3 | **12** |
| `governance-audit` | `/governance/audit` | 2 | 2 | — | 3 | **12** |
| `governance-controls` | `/governance/controls` | **1 — VC-R2**: inert specification, no read model | 2 | — | 3 | **6** |
| `system-data-quality` | `/system/data-quality` | 2 | 2 | — | 3 | **12** |
| `system-operations` | `/system/operations` | 2 | 2 | — | 3 | **12** |
| `system-alerts` | `/system/alerts` | 2 | 2 | — | 3 | **12** |
| `foundation-states` | `/foundation/states` | **1 — VC-R3**: the state reference renders every state in `demo` by design | **1 — VC-R3** | — | 3 | **3** |

**Nominal total: 50 + 28 × 12 + 2 × 6 + 3 = 401 snapshots**, of which **nine exist today** — the three
existing captures (`overview-demo-executive`, `overview-project`, `availability-states`) at the three
original widths, which map onto `VC-root-demo-executive`, `VC-root-project-executive` and
`VC-foundation-states-demo-executive` and are **kept, byte-identical, under their existing names**.
**The count is nominal**: an implementer confirms each route's axes against the read models it
renders and records any VC-R declaration in the acceptance record. **A declared inapplicability that
cites no rule is a gap, and the row reads `PARTIAL`.**

### 4.3 The applicability rules — VC-R1 to VC-R5

| Rule | A combination is inapplicable when | Evidence required in the inventory |
|---|---|---|
| **VC-R1** | the route renders **only `REPOSITORY_TRACKED`** read models, so the scenario axis changes no pixel | the read-model provenance, cited to the contracts document |
| **VC-R2** | the route renders **no read model** (the inert control plane), so the scenario axis is meaningless | the registry `status: "inert"` |
| **VC-R3** | the route is a **foundation reference surface** whose purpose is to render every state at once | the registry group `foundation` |
| **VC-R4** | a declared **variant** is unreachable in a scenario by contract (the `changes` variants exist only inside the labelled synthetic scenario) | the scope module's own comment |
| **VC-R5** | a **shared component** is already captured on a reference screen and the route adds no distinct arrangement of it — **applies to component-level snapshots only**; it **never** exempts a route |

**No rule exempts a viewport in VC-I3's list, and no rule exempts a mode.** Operator mode changes
every read-model panel's rendering, so it is never inapplicable on a read-model route.

### 4.4 What a visual snapshot is, and what it is not

| Check | Answers | Owned by |
|---|---|---|
| **visual snapshot** | *does this route in this state at this width still look exactly as it did?* | this inventory |
| **responsive / structural sweep** | *does anything overflow, clip, lose its `h1`, its landmark, its context bar or its label?* | `c10-acceptance.spec.ts`, `c10-reference-viewports.spec.ts` — every route, all six viewports |
| **behavioural** | *does the palette open, does the mode switch preserve context, does a link go where it says?* | the per-cycle specs |
| **accessibility** | *does axe find a violation; can a person using a screen reader complete the journey?* | `c10-acceptance.spec.ts` for the automated half; **§5 for the manual half** |

A snapshot passing says nothing about the other three, and the other three passing says nothing
about a snapshot. **The six-viewport structural sweep is why VC-I3 can stop at three widths for
most routes without losing the §12 checks at the other three.**

### 4.5 Capture conditions, state setup, baseline provenance, review and failure handling

| | |
|---|---|
| **deterministic capture** | exactly the existing recipe, unchanged: the clock frozen at the fixed instant with `page.clock.setFixedTime`, `reducedMotion: "reduce"`, `animations: "disabled"`, `caret: "hide"`, `scale: "css"`, the repository's seeded fixtures, and **nothing masked** — *"a mask is a promise not to look"* |
| **state setup** | **from the URL only** — `scenario`, `mode`, and the declared variant parameter — so every state is reproducible by anyone from the snapshot's name. No state is set up by clicking, by injecting a script or by editing a fixture |
| **precondition** | the existing `settle` wait (freshness indicator and context bar visible) plus the route's own populated marker, at the existing 30-second precondition; **the comparison tolerance is untouched by the precondition** |
| **tolerance** | **`threshold: 0`, `maxDiffPixels: 0`, `maxDiffPixelRatio: 0` for every image**, exactly as the nine existing comparisons are today. **This ADR proposes no other tolerance for any image**; a different policy would be a separate proposal, justified on its own evidence, and none is made |
| **baseline provenance** | every baseline is **platform-scoped in its file name** (the existing `{platform}` template), and the pull request that adds or regenerates one records the **tree it was captured from, the OS, the browser build and the command**. A baseline with no recorded provenance is not a baseline |
| **review of updates** | **a diff is a review item, not an auto-accept.** A baseline update is a pull request whose description lists each changed image with the reason the pixels moved; the reviewer opens the diff. **`--update-snapshots` is never run to make a failing comparison pass**; it is run to record a reviewed, intended change |
| **failure handling** | a failed comparison **fails the gate**. The trace and the diff image are retained; the failure is either a defect (fix the code) or an intended change (regenerate **and review**). **No masking, no tolerance increase and no automatic regeneration is a permitted response to a failed comparison** |
| **missing baseline** | on a platform with no committed baseline the suite **reports the snapshot missing and fails**, exactly as today; it never accepts what it finds |

### 4.6 What acceptance of VC establishes — and what it does not

**It establishes the inventory and the rules. It captures nothing.** Nine of 401 nominal snapshots
exist; **no new baseline is created by this ADR or its pull request**, no test is implemented, and
the §15 visual-regression row stays **`PARTIAL`** until the inventory is captured, reviewed and read
into the acceptance record. The rows the M decision adds are capturable only after M is implemented.

---

## 5. Decision SR — a manual screen-reader assessment that a person can actually run

### 5.1 The rule this decision exists to keep

**An automated axe pass is not a screen-reader assessment, source inspection is not one, and neither
may be recorded as one.** §15 asks for *"manual keyboard and screen-reader passes, because an
automated pass is not an accessible interface"*, and the acceptance record records the pass as
`NOT_ASSESSED` because no assistive technology was available to either session. **That disposition
stands until a person runs this protocol.**

### 5.2 The assessor and the assistive technology

| | |
|---|---|
| **assessor** | **one named human assessor who did not author the C10 implementation**, recorded by role and by the fact of the assignment — the person's identity stays out of this repository. **No assessor is currently identified: the assignment is OUTSTANDING**, and nothing here invents one |
| **primary combination** | **NVDA + Chrome on Windows 11** — the platform this repository is developed, tested and baselined on. The **actual NVDA, Chrome and Windows build versions are recorded at execution**, not predicted here |
| **secondary combination** | **VoiceOver + Safari on macOS**, **if** a macOS assessor and device are available; otherwise recorded as `NOT AVAILABLE` rather than assumed. **No availability of any assistive technology is claimed here** |
| **installation** | **nothing is installed by this ADR**. Installing a screen reader on an assessment machine is the assessor's preparation, recorded in the evidence sheet |
| **viewports** | **1440 × 900** for every journey; **390 × 844** for J8 and for J1 repeated; **200 % zoom** for J10 |
| **server** | a production build (`next build`, `next start`) on loopback, so what is heard is the application and not the development server's overlay |

### 5.3 Journeys and route coverage, traced to accepted requirements

**Every registered route gets the structural pass (SR-A); eight journeys get the full protocol.**

| Journey | Steps | Traced to |
|---|---|---|
| **J1 — the ten seconds** | land on `/` in `demo`; hear the `h1`; navigate the six tier-1 tiles by heading and by landmark; hear each question, subject, value **with unit**, provenance and availability; follow one tile's link and return | §2, §6, U1, U2, U3, U11, U19 |
| **J2 — attention to evidence** | on `/`, reach the attention panel; hear what happened, why it matters, impact, evidence and the permitted action for the first item; expand its evidence disclosure; follow an evidence reference to its owning area | §6, Area 28, ADR-0031 |
| **J3 — ledger to detail** | `/portfolio/trades`: use the skip-to-table link; navigate the table by column and row headers; open one trade's detail; hear the lifecycle; return | §8, §10, Area 36, U14 |
| **J4 — the palette** | from a deep route, `Ctrl+K`; hear the dialog announced; type a route name; hear results; `Escape`; confirm focus returned to the invoking element | §10, U8, U9 |
| **J5 — the states** | `/foundation/states`: hear each of the eleven availability states read distinctly, and hear that none reads as a value | §9.2, U4, U5 |
| **J6 — what changed** | `/?scenario=demo&changes=degraded` and `changes=no-baseline`: hear the item report a state rather than a delta | §7, U17 |
| **J7 — charts** | `/portfolio/performance`: reach the chart's table alternative by keyboard; hear the same series values the chart plots | §11, U10 |
| **J8 — mobile summary** | at 390 × 844, `/`: hear the summary sections; hear each disclosure announced with its expanded/collapsed state; expand each; confirm every deferred section is reachable and its heading is listed. **Runs only once Decision M is implemented; until then recorded `NOT APPLICABLE — M NOT IMPLEMENTED`** | §12, M5, M8 |
| **J9 — the inert plane** | `/governance/controls`: hear that every control is inert and that nothing accepts input | U16 |
| **J10 — zoom** | J1 repeated at 200 % zoom | §11 zoom |
| **SR-A — every route** | for each of the thirty registered routes: one `h1` announced; the `main` landmark reachable; the heading list in order with no skipped level; the context bar's environment, source and freshness read | §11 semantic structure, U2 |

### 5.4 What is checked in each journey

| Check | Expected |
|---|---|
| **headings and landmarks** | one `h1`; heading list navigable in order; `main`, `navigation`, `banner` landmarks named and unique where repeated (`landmark-unique`) |
| **names** | every link and control has a distinct, meaningful accessible name — no two *"Open the area that owns this"* without a subject, no icon-only control without a name |
| **tables** | column and row headers announced with cells; the table's caption or accessible name announced; sortable headers announce their sort state |
| **dialogs** | the palette announced as a dialog; focus trapped while open; `Escape` closes it and **restores focus to the invoking element** |
| **disclosures** | expanded/collapsed state announced on focus and on toggle; focus stays on the control after a toggle |
| **loading** | a pending panel is announced as busy or not at all — **never as a value**, and never as "0" |
| **availability and freshness announcements** | a change in availability or freshness is announced **politely** (a `polite` live region), never assertively; the announced text names the state |
| **errors** | an `ERROR` widget announces its state and its reason code, and the page is still navigable around it |
| **focus restoration** | after every dialog, drawer or navigation-and-back, focus is where a keyboard user would expect it |

### 5.5 The keyboard-only pass is separate evidence

**Two sessions, two evidence sheets.** The keyboard-only pass is run **without** a screen reader,
with the focus ring visible, and establishes: every interactive element reachable in reading order,
no keyboard trap (charts and virtualized tables included), skip links to main content and to the
primary table working, `Escape` closing exactly one layer. **A passing keyboard pass is not a
screen-reader pass, and neither is reported under the other's row.**

### 5.6 Expected outcomes, severity, evidence and closure

| Severity | Meaning | Effect on the disposition |
|---|---|---|
| **S1 — blocker** | a journey cannot be completed with the assistive technology | **fails** the assessment |
| **S2 — major** | a journey completes but a required fact is not announced, is announced wrongly, or a state is announced as a value | **fails** the assessment |
| **S3 — minor** | verbosity, ordering or redundancy that does not change what is understood | recorded; **does not fail**; becomes a follow-up |
| **S4 — advisory** | an improvement with no accepted requirement behind it | recorded, not counted |

| | |
|---|---|
| **evidence** | one dated protocol sheet per journey: assistive technology, browser and OS **versions as observed**; viewport; route; scope URL; a short transcript excerpt of each announcement that supports a finding; the finding's severity and the clause it fails. Sheets are stored as sanitized Markdown under `docs/cockpit/accessibility/` — **no private identifier, no assessor name, no screenshot of anything but the Cockpit over fixtures** |
| **closure** | the §15 manual pass reads **`ASSESSED — PASSED`** only when **every journey and SR-A on the primary combination has been run by the named assessor with zero S1 and zero S2 findings**, and the sheets are in the tracked tree. It reads **`ASSESSED — FAILED`** with the findings listed otherwise. **It reads `NOT_ASSESSED` until then**, whatever the automated checks say |
| **who can establish it** | **only the assessor, running the protocol.** Not the author, not an axe run, not a reviewer reading source, not this ADR |

### 5.7 What acceptance of SR establishes — and what it does not

**It establishes the protocol. It runs nothing.** No assessor is assigned, no assistive technology is
available in the sessions that wrote or will review this ADR, and no announcement has been heard.
**The manual screen-reader pass stays `NOT_ASSESSED`.**

---

## 6. Acceptance accounting — the remaining C10 criteria, mapped

**Four columns, and they are not one.** *Contract defined* is this ADR on acceptance; *implemented*
is a later cycle's code; *tested* is that cycle's evidence; *accepted* is a human reading that
evidence against the contract. **Every row below is at the first column at most, and "at most" is
doing work: while this pull request is open, none is even there.**

| Remaining criterion | Accepted requirement | Proposed decision | Implementation or assessment still required | Evidence required for closure | Who or what establishes it | Contract · Implemented · Tested · Accepted |
|---|---|---|---|---|---|---|
| **§12 mobile executive summary** | `ui-ux-specification.md` §12, 390 × 844 row | **Decision M** (§2) | an implementation cycle building M1–M7 on `/` | the M8 tests passing at 390 × 844 and at every wider viewport; the two M rows of the VC inventory captured | a later authorized cycle, then its independent review | **proposed · no · no · no** |
| **§15 performance targets** | `ui-ux-specification.md` §15, performance row | **Decision PB** (§3) | correcting the PB2 measurement; a Condition L run under §3.3–§3.7 for the seven routes; a Condition M run | the retained evidence file with every sample, versions and tree; every budget reported `PASS`, `FAIL` or `NOT OBTAINED` per route; read into the acceptance record | a later authorized measurement cycle | **proposed · n/a · no · no** |
| **§15 visual regression** | `ui-ux-specification.md` §15, screenshot row | **Decision VC** (§4) | capturing the inventory at the stated conditions; recording provenance; the reviewed pull request that adds the baselines | 401 nominal snapshots, or fewer with every gap cited to a VC-R rule and the row read `PARTIAL`; the nine existing images unchanged | a later authorized cycle, then its independent review of the diff | **proposed · 9 of 401 · 9 of 401 · no** |
| **§15 / §11 manual screen-reader pass** | `ui-ux-specification.md` §11 and §15, accessibility row | **Decision SR** (§5) | assigning an assessor — **OUTSTANDING**; running J1–J10 and SR-A on the primary combination | the protocol sheets under `docs/cockpit/accessibility/`, zero S1/S2 | **the named assessor only** | **proposed · n/a · no · no** |

**C10's §15 assessment is one of four, and this ADR does not move it.** Accepting definitions
changes what the next cycle must show; it shows nothing itself.

---

## 7. Carried forward, and deliberately not absorbed

**Each of these is recorded so it is not read as closed, and none is resolved by this ADR.**

```text
rejected reads render like pending reads          a ReadModelPanel cannot distinguish a rejected
                                                  read from a pending one -- both render the
                                                  skeleton. An observability limitation of the
                                                  application; UNCHANGED, and NOT a proposal here
reuseExistingServer provenance risk               the suite reuses whatever server is listening on
                                                  its port; the evidence file DESCRIBES the server
                                                  and cannot PROVE which one answered. PB requires
                                                  the description; it does not remove the risk
the intermittent client-render failure            two full-suite failures on PR #87, after the
                                                  document response and before the first client
                                                  render; the cause is NOT ESTABLISHED. Tracing is
                                                  retained on failure; nothing here diagnoses it
capacity diagnostic limitations                   some capacity declaration failures refuse with an
                                                  empty missing-input list; the declaration-to-input
                                                  mapping stays UNRESOLVED; the nine required inputs
                                                  do not exist
original PR #84 Linux review evidence             UNAVAILABLE. The two Windows verification sets are
                                                  separate evidence with separate provenance, and
                                                  neither recovers it
C5 and C7                                         NOT COMPLETE, for the requirements the acceptance
                                                  record names; full Cockpit V1 INCOMPLETE
```

---

## 8. Alternatives considered

| Alternative | Why not |
|---|---|
| **M — omit the non-summary sections at mobile** | removes specified executive information (Area 1 *Presents*) with **no route to reach it**, because none owns What Changed or tier 2; §12's own tail shows the section never intended mobile to lose content |
| **M — move What Changed and tier 2 to new routes** | invents destinations the accepted route map (§3) does not have; a route is a specification change with its own area ownership, not a responsive adjustment |
| **M — a tabbed mobile layout** | tabs hide the heading structure of unselected panels from heading navigation and are a different interaction model from the disclosures the application already uses |
| **M — breakpoint at 768 px** | would put the tablet-portrait row under the summary rule, contradicting §12's *"single-column stacking"* for 768 × 1024 |
| **PB — budgets set to today's production figures** | a budget met by construction constrains nothing and would fail the moment a real read boundary landed; the proposed figures bound growth instead |
| **PB — budgets against `next dev`** | describes the development server's compilation, not the application |
| **PB — a percentile with five samples** | p90 of five is the maximum; stating *no sample above* says what is actually checked |
| **PB — a number for bounded query time now** | would time an in-process fixture call and describe no read API |
| **VC — the full Cartesian product** | not required by §15's words; roughly 800 images; hundreds of diffs per intended design change; the structural sweep already checks the other three widths |
| **VC — three widths for `/` too** | §12 states distinct per-viewport requirements for the Executive Overview on four of six rows, so `/` is the one route where all six widths carry a stated requirement |
| **VC — a tolerance above zero for new images** | the review measured the default tolerance **inert** against a visible colour change; zero is what made the baseline a baseline. No evidence justifies a different policy for any image |
| **SR — record the axe result as the manual pass** | §15 says in as many words that an automated pass is not one; the record says `NOT_ASSESSED` for exactly this reason |
| **SR — assign an assessor in this ADR** | nobody is available to be named; inventing one is a false record |

---

## 9. Consequences

### 9.1 What becomes true on acceptance

- The §12 mobile row has a definition (M), the §15 performance row has budgets and conditions (PB),
  the §15 visual row has an inventory and rules (VC), and the §15 accessibility row has a protocol
  (SR) — **each as an acceptance definition, and none as a result**.
- A later implementation, measurement or assessment cycle can be authorized against a stated
  finish line rather than against an ambiguity.
- The existing implementation **is not made to fail an accepted contract by this acceptance**: no
  budget is asserted in the performance spec, no snapshot is added, no mobile assertion changes,
  because acceptance defines and does not enforce. Enforcement is the later cycle's, once it has
  something to enforce against.

### 9.2 What does not change

- **U1–U20**, every §12 row's existing requirement, §5, §6, §7, §8, §9, §10 and §11 — unchanged.
- **The nine committed baselines and their zero tolerance** — unchanged, byte for byte.
- **The performance spec's assertions** — unchanged: each measurement obtained and positive, no
  budget asserted, until a measurement cycle is authorized to assert PB.
- **The acceptance record's dispositions** — `NOT SATISFIED`, `PARTIAL`, `PARTIAL`, `NOT_ASSESSED`,
  and **§15 at one of four**.
- **Every standing limit** in §10 below.

### 9.3 What stays open

- **Who assesses.** The SR assessor assignment is OUTSTANDING.
- **Why the paint entry was absent.** PB2's `NOT OBTAINED` has a proposed correction and no
  established cause.
- **Condition F.** No deployed budget exists because nothing is deployed.
- **PB-Q.** Bounded query time waits on a read-model boundary that does not exist.
- **The client-render failure's cause**, the rejected-versus-pending rendering, the capacity mapping
  and the PR #84 Linux evidence — carried forward in §7, unchanged.

---

## 10. What this decision does not do

```text
implements NO user interface                 launches NO browser suite
creates or regenerates NO screenshot         takes NO performance measurement
installs NO software or dependency           configures NO CI
assigns NO assessor                          claims NO human assessment occurred
edits NO accepted criterion U1-U20           edits NO other ADR
changes NO tolerance on any existing image   changes NO fixture, contract or read model
moves C10's section 15 assessment: NO -- ONE OF FOUR, UNCHANGED
completes C10, C5, C7 or Cockpit V1: NO
```

```text
Run A:                                    COMPLETED ONCE, 2026-09-04 -- retry NOT AUTHORIZED
Run B:                                    NOT RUN / NOT AUTHORIZED -- 2026-09-12 is eligibility, not permission
combined assessment:                      NOT RUN / NOT AUTHORIZED
P1-P9:                                    UNEVALUATED
data correctness and quality:             NOT ESTABLISHED
G1 / G2:                                  OPEN / OPEN
G3:                                       CLOSED -- within the personal-use scope only
G4-G7:                                    OPEN
provider selected:                        NONE
backtesting:                              NOT STARTED
Phase 3:                                  NOT COMPLETE
ADR-0005:                                 PROPOSED
INC-0002:                                 OPEN
CONTROL:                                  DEFERRED
live trading:                             HARD-DISABLED
Brain runtime and research/feedback automation:  NOT IMPLEMENTED / NOT AUTHORIZED
C5 / C7 / C10 / full Cockpit V1:          INCOMPLETE
```

**Specification, implementation, research, deployment and execution stay five separate gates**, and
this decision is entirely within the first.
