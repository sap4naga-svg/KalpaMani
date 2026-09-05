# Cockpit — UI and UX specification

**Status: ACCEPTED SPECIFICATION EFFECTIVE ON MERGE OF PR #NNN, and PROPOSED until that merge —
NOT IMPLEMENTED, NOT AUTHORIZED.**

This document specifies presentation and interaction: information architecture, design tokens,
states, keyboard behaviour, accessibility, responsiveness and the observable acceptance criteria a
later implementation cycle must satisfy.

**It specifies. It does not implement, and it authorizes nothing.** No component, stylesheet, token
file, route or screenshot exists because this document describes one.

**Introduced by** [ADR-0027](../decisions/ADR-0027-cockpit-and-feedback-architecture-and-governance.md).

---

## 1. The visual direction, and what was actually established

**The owner supplied a benchmark reference:** <https://atlasaicopilot.com/sire>.

**It is treated as owner-supplied visual direction and nothing more.** Two things are recorded
plainly, because the alternative is a specification that pretends to have looked at something:

| | |
|---|---|
| **no retrieval was performed in this cycle** | this document was authored from the written brief. **No claim is made about any inspected design**, and none about that page's content, layout, components or behaviour |
| **a coordinator retrieval returned 404** | that is a fact about that attempt and nothing more. It **does not block this specification**, and it establishes nothing about the site |

**No claim is made about Atlas or SIRE's internal technology stack**, and none was inspected. A
visual benchmark is a direction; it is not evidence of how anyone built anything.

**The design brief, stated explicitly, is what this specification is designed from:**

> **SIRE executive philosophy + institutional portfolio manager + modern AI command center.**

Decomposed into properties that can actually be checked:

| Influence | What it contributes |
|---|---|
| **executive philosophy** | few numbers, chosen deliberately · answers before detail · calm, not busy · the important thing is the largest thing on the screen |
| **institutional portfolio manager** | precise numerics · tabular density where density is the point · provenance and as-of times treated as first-class, not as footnotes · no decoration that could be mistaken for data |
| **modern AI command center** | keyboard-first navigation · a command palette · natural-language querying with cited evidence · explanations that link to the record that produced them |

---

## 2. The ten-second test

**The default Executive view must answer five questions in roughly ten seconds:**

```text
How are we doing?          Is anything wrong?          What changed?
Where is risk?             What requires attention?
```

**That is an acceptance criterion, not an aspiration.** It constrains the layout: the five answers
occupy the first viewport at the reference desktop width, without scrolling, and each links to the
area that owns it.

**Operator mode exposes evidence and technical detail through drill-down** — reason codes, versions,
lineage, raw contributing values and the projection state that produced them.

---

## 3. Information architecture and route map

**Grouped navigation.** Thirty-six areas are not thirty-six equal-weight sidebar links; a flat list
of 36 destinations is an unusable interface, and the grouping is part of the specification.

```text
/                                       Executive Overview                      (area 1, 28, 29)
/attention                              Attention Required                      (area 28)

/portfolio/performance                  Portfolio Performance                   (area 2)
/portfolio/positions                    Positions & Exposure                    (area 3)
/portfolio/trades                       Trade History                           (area 36)
/portfolio/trades/[tradeId]             Trade Detail                            (area 36)

/strategy/performance                   Strategy Performance                    (area 4)
/strategy/health                        Strategy Health                         (area 5)
/strategy/champion-challenger           Champion / Challenger                   (area 15)
/strategy/versions                      Strategy Version Registry               (area 20)

/signals/funnel                         Signal & Candidate Funnel               (area 6)
/signals/candidates/[candidateId]       Candidate Detail / Explainability       (area 7)
/signals/missed                         Missed Opportunities                    (area 8)

/risk                                   Risk Dashboard                          (area 12)
/risk/short-side                        Short-Side Dashboard                    (area 13)
/market/regime                          Market & Regime                         (area 11)

/execution/quality                      Execution Quality                       (area 9)
/execution/reconciliation               Broker & Reconciliation                 (area 10)

/research/runs                          Research & Backtesting                  (area 14)
/research/queue                         Research Queue                          (area 17)
/research/hypotheses                    Hypothesis Registry                     (area 18)
/research/feedback                      Feedback / Self-Maturation Loop         (area 16)
/research/ai-contribution               AI Contribution Analytics               (area 21)

/governance/packets                     Governance Packets                      (area 19)
/governance/qualification               Project & Qualification Governance      (area 24)
/governance/maturity                    Environment & Deployment Maturity       (area 25)
/governance/audit                       Audit Trail                             (area 26)
/governance/controls                    Future Control Plane -- INERT           (area 35)

/system/data-quality                    Data Quality & PIT                      (area 22)
/system/operations                      System Operations                       (area 23)
/system/alerts                          Alerts & Exceptions                     (area 27)
```

**Global surfaces**, present on every route: the command palette (area 30), Ask KalpaMani (area 31),
the Executive/Operator mode switch (area 29), and the persistent environment, source and freshness
header (areas 32, 33).

**`/governance/controls` renders an inert specification of the future control plane.** No control
has a handler, and **no control API route exists** — a disabled button whose handler exists is not
inert.

**Drill-down paths are explicit**, so no view is a dead end:

```text
Executive tile        -> the area that owns the number
Attention item        -> its evidence -> the record that produced it
Strategy              -> health -> transition history -> the research queue item it created
Candidate             -> explainability -> evidence -> lineage -> audit events
Trade                 -> Trade Detail -> lifecycle -> execution mechanics -> audit events
Research run          -> its registration -> its trial budget -> its governance packet
```

---

## 4. Design tokens

**Tokens, not values scattered through components.** The names below are the contract; the exact
values are an implementation choice within the stated constraints, and both light-independent dark
surfaces and semantic statuses are required.

### 4.1 Surfaces and structure

```text
--surface-base            the page ground -- deep, neutral, low chroma
--surface-raised          cards and panels, one step above base
--surface-overlay         popovers, palette, dialogs
--surface-sunken          table headers, inset regions
--border-subtle           hairlines that separate without drawing attention
--border-strong           deliberate separation and focus containers
--elevation-1 / -2        restrained shadow; never a glow
```

**Dark-first, and calm.** The base is a deep neutral, not black, and not a saturated navy that tints
every number on top of it. **No neon, no terminal green, no glow.**

### 4.2 Text

```text
--text-primary            principal values and headings
--text-secondary          labels and supporting copy
--text-tertiary           metadata, as-of times, provenance
--text-inverse            on accent surfaces
```

Contrast requirements are in §11.

### 4.3 Accents and semantic statuses

```text
--accent                  ONE accent, used sparingly, for the primary interactive affordance
--positive                gains and healthy states
--negative                losses and failures
--warning                 degradation and staleness
--info                    neutral emphasis
--unavailable             the availability states -- deliberately LOW-CHROMA and never alarming
```

**Restraint is a rule.** The accent appears on a small number of elements per screen. **Semantic
colour is reserved for meaning**, so a coloured element on a Cockpit screen always means something.

**`--unavailable` is deliberately not red.** `NOT_IMPLEMENTED` is not an error, and rendering it as
one trains a reader to ignore real errors.

### 4.4 Typography and numerics

```text
--font-sans               interface text
--font-mono               EVERY number, identifier, code and timestamp
--numeric-xl / -l / -m / -s
--label-m / -s
```

| | |
|---|---|
| **tabular figures everywhere** | numbers align in columns, and a digit change does not reflow a row |
| **numeric hierarchy** | one primary number per tile, its comparison secondary, its metadata tertiary. Three sizes, not five |
| **units are always shown** | currency, percentage, R, days, basis points. **A bare number is not a metric** |
| **signs are explicit** | a positive value shows its sign where sign is meaningful, and colour is never the only carrier of direction |
| **precision is per metric** | declared by the metric dictionary, not chosen per component |

### 4.5 Spacing, radius, motion

```text
--space-1 .. --space-12   a single spacing scale
--radius-sm / -md / -lg
--motion-fast / -base     short, purposeful transitions only
```

**Generous whitespace is load-bearing** for the executive brief. Density belongs in tables, not in
the overview.

---

## 5. Persistent environment, source and freshness

**Three indicators are present on every route, in the header, at all times.**

| Indicator | Shows |
|---|---|
| **environment** | the runtime environment and the maturity scope of what is displayed |
| **source** | `DataProvenance` — and **`SYNTHETIC` is unmissable**, not a tooltip |
| **freshness** | the as-of time of the newest contributing projection, and its staleness state |

**A synthetic deployment is labelled at page level and at component level.** A screenshot of one
tile must still show that it is synthetic, because screenshots travel.

**Scoping travels with everything.** Cache keys, filters, URLs, exports, deep links and assistant
queries all carry environment and source, so a shared link cannot open under a different environment
than the one it was captured in.

**No silent cross-environment aggregation.** An explicit comparison shows separately labelled series
and separately labelled results. **An "all environments" trade search never implies a meaningful
combined profit and loss** across backtest, shadow, paper and live copies of the same trade — it
groups by environment and says so.

---

## 6. KPI hierarchy and Attention Required

**The Executive Overview has exactly three tiers**, and the tiering is the specification:

```text
TIER 1   the five ten-second answers -- large numerics, first viewport, no scrolling
TIER 2   supporting context -- exposure, regime, freshness, active strategies
TIER 3   What Changed, and the ranked Attention Required list
```

**Attention Required sits in the first viewport at the reference desktop width**, because an
attention list below the fold is a list nobody reads.

**Every attention item shows five things**, and an item missing any of them is not rendered:

```text
what happened      why it matters      impact
evidence           the recommended permitted governance action
```

**Ranked by materiality and severity, and deduplicated against the alert feed.** A recommended
action is always a **permitted governance action** and never an execution instruction — and the
Cockpit performs none of them.

---

## 7. What Changed

**A comparison needs a stated baseline, and this one says it on the screen.**

| | |
|---|---|
| **the comparison window is explicit** | "since yesterday's close", "since last Friday", "since the last decision run" — chosen by the reader and displayed |
| **the baseline as-of is shown** | both endpoints carry their as-of times |
| **appearances and disappearances are changes** | a strategy entering `DEGRADED` and an alert clearing are both shown |
| **an unavailable endpoint is not a change** | when either side is `NOT_YET_AVAILABLE`, `STALE` or `PARTIAL`, the item reports that instead of a delta. **A delta computed against a missing baseline is a fabricated change** |
| **no synthetic-to-real comparison** | two provenances never form one delta |

---

## 8. Tables, filters and saved context

| | |
|---|---|
| **column priority is declared** | each table declares its columns in priority order; narrow viewports drop from the bottom of that order, never arbitrarily |
| **identity columns never drop** | the columns that identify the row, and its environment and provenance, are always present |
| **filter chips** | active filters are visible as removable chips. **A filter that is applied but invisible is how a reader misreads a subset as the whole** |
| **date ranges** | explicit, with the calendar basis and timezone shown |
| **saved context** | filters, ranges, mode and scoping survive navigation and mode switching within a session, and are encoded in the URL so a link reproduces the view |
| **wide content scrolls inside itself** | a table, a chart or a code block scrolls in its own container. **The page body never scrolls horizontally** |

---

## 9. States

### 9.1 Page-level and widget-level failure are different

**A failing widget does not fail the page.** Each widget renders its own availability, and the page
reports itself `PARTIAL` when any widget is degraded. A page-level `ERROR` is reserved for a failure
that makes the whole view meaningless.

### 9.2 Empty, unavailable and stale are visually distinct

| State | How it reads |
|---|---|
| `EMPTY_VERIFIED` | "no rows, and that is the correct answer" — neutral, with its as-of time |
| `NOT_YET_AVAILABLE` | "specified, not yet fed" — with the dependency named |
| `NOT_IMPLEMENTED` | "the producing subsystem does not exist" — low-chroma, not an error |
| `NOT_AUTHORIZED` | "exists, may not run" — with the authorization named |
| `UNEVALUATED` | "not assessed" — never "pending", never blank, never zero |
| `STALE` | the value **with** its age and its freshness contract, visually marked |
| `PARTIAL` | the available extent, with the missing extent stated |
| `ERROR` | a failure, with a closed reason code and **no fabricated payload** |
| `INSUFFICIENT_OBSERVATIONS` | the observation count and the minimum required, **and no ratio** |

**Three distinctions are acceptance criteria**, because collapsing any of them is the failure this
section exists to prevent:

```text
EMPTY_VERIFIED        is not   NOT_YET_AVAILABLE
NOT_IMPLEMENTED       is not   NOT_AUTHORIZED
STALE                 is not   AVAILABLE
```

**No availability state is ever rendered as zero, healthy, passed or no incidents.**

### 9.3 Loading

**A loading skeleton never resembles a real value.** Skeletons are shape-only — no digits, no
plausible placeholder numbers, no "0.00" while loading, and no last-known value presented as
current. A screenshot taken mid-load must not be mistakable for data.

---

## 10. Keyboard, focus and the command palette

| | |
|---|---|
| **`Cmd/Ctrl+K`** | opens the command palette from anywhere, including from within a dialog |
| **`Escape`** | closes the topmost layer only, and returns focus to the element that opened it |
| **focus is always visible** | a visible focus ring on every interactive element, meeting the contrast requirement in §11 |
| **focus is trapped in modals** | and released on close, to the invoking element |
| **tab order follows reading order** | and skip links reach the main content and the primary table |
| **no keyboard trap** | anywhere, including inside charts and virtualized tables |
| **palette has no execution verb** | it navigates, searches and filters. **The command vocabulary is closed**, so a later author cannot add a verb casually |

---

## 11. Accessibility

**Targets for a later implementation cycle. This cycle claims none of them as achieved**, because
nothing has been built to measure.

| | |
|---|---|
| **contrast** | WCAG 2.2 AA — at least 4.5:1 for body text and at least 3:1 for large text, interactive boundaries and focus indicators |
| **non-colour cues** | every status carries a shape, an icon or a label in addition to colour. **Colour is never the only carrier of meaning**, and red/green profit-and-loss is always accompanied by a sign |
| **charts have accessible alternatives** | every chart has a semantic text or table alternative conveying the same information, reachable by keyboard and by a screen reader |
| **semantic structure** | landmarks, one `h1` per page, ordered headings, labelled form controls, and tables with real headers and scopes |
| **live regions** | availability and freshness changes are announced politely, and never as assertive interruptions |
| **reduced motion** | `prefers-reduced-motion` removes transitions and animated chart transitions; nothing animates as its only way of conveying a change |
| **target size** | interactive targets meet the minimum pointer target size on touch viewports |
| **zoom** | usable at 200% zoom without loss of content or functionality |

---

## 12. Responsiveness

**Desktop-first, excellent on tablet, useful on mobile.** The mobile target is deliberately narrow:
**an executive summary**, not a scaled-down operator console.

| Reference viewport | Requirement |
|---|---|
| **1920 × 1080** | full executive layout; tier 1 and Attention Required within the first viewport, no scroll |
| **1440 × 900** | the reference desktop width. Tier 1 and Attention Required within the first viewport, no scroll |
| **1280 × 800** | full navigation; tables may drop lowest-priority columns |
| **1024 × 768** | tablet landscape; grouped navigation collapses to a rail; charts reflow |
| **768 × 1024** | tablet portrait; single-column stacking; tables scroll within their own container |
| **390 × 844** | mobile; **executive summary only** — tier 1, Attention Required and search. Operator tables are reachable and explicitly narrow |

**At every viewport:** no horizontal page scroll · no clipped critical control · no truncated number
without a full value available · charts remain legible or are replaced by their accessible
alternative rather than shrunk into illegibility.

---

## 13. Charts

| Class | Library | Used for |
|---|---|---|
| **executive and time series** | Recharts | KPI trends, equity and drawdown curves, ordinary comparisons |
| **price and trade overlays** | TradingView Lightweight Charts | OHLC and candles, Trade Detail entry, add, stop and exit markers |
| **dense analytics** | Apache ECharts, selectively | correlation matrices, return heatmaps, factor and regime matrices |

**The boundary is specified so it is not decided per screen.** A chart carries its provenance, its
as-of time and its availability like every other component, and **a series with mixed provenance is
never drawn as one line**.

---

## 14. Observable acceptance criteria

**Each is checkable by a person or by a test, against a synthetic fixture set.**

| # | Criterion |
|---|---|
| **U1** | at 1440 × 900, the Executive Overview answers the five ten-second questions within the first viewport, without scrolling |
| **U2** | environment, source and freshness are visible on every route, at all times |
| **U3** | a `SYNTHETIC` deployment is labelled at page level **and** at component level |
| **U4** | every one of the eleven availability states renders distinctly, and none renders as zero or as a healthy value |
| **U5** | `EMPTY_VERIFIED`, `NOT_YET_AVAILABLE`, `NOT_IMPLEMENTED`, `NOT_AUTHORIZED` and `STALE` are visually distinguishable from one another |
| **U6** | a failing widget leaves the rest of the page usable, and the page reports `PARTIAL` |
| **U7** | a loading skeleton contains no digits and no plausible placeholder value |
| **U8** | `Cmd/Ctrl+K` opens the palette from every route; `Escape` closes exactly one layer and restores focus |
| **U9** | the palette exposes **no** state-changing verb |
| **U10** | every chart has a keyboard-reachable, screen-reader-readable alternative with the same information |
| **U11** | no status is conveyed by colour alone |
| **U12** | `prefers-reduced-motion` removes every non-essential transition |
| **U13** | filters, date range, mode and scoping survive a mode switch and are reproducible from the URL |
| **U14** | no page scrolls horizontally at any reference viewport; wide content scrolls within its own container |
| **U15** | mode switching preserves drill-down context and does not reset the view |
| **U16** | every future control on `/governance/controls` is inert, and **no control API route exists** |
| **U17** | a What Changed item with an unavailable endpoint reports that state instead of a delta |
| **U18** | an "all environments" search groups by environment and presents no combined result |
| **U19** | every displayed metric shows its unit, and every ratio its denominator or its `NOT_APPLICABLE` state |
| **U20** | no owner private identifier, vendor row, account, bucket, locator or broker-native order id appears anywhere in the rendered interface |

---

## 15. Future visual and end-to-end criteria

**Specified now, implemented in a later cycle.**

| | |
|---|---|
| **screenshot and visual regression** | a fixed synthetic fixture set, a fixed viewport list, deterministic rendering, and a stable baseline per route and per state. A diff is a review item, not an auto-accept |
| **synthetic end-to-end** | navigation across every route, every availability state rendered at least once, drill-down paths traversed, mode switching with context preserved, palette open and close, and every failure state exercised deliberately |
| **accessibility checks** | automated contrast, landmark, heading-order and label checks in the pipeline, with **manual keyboard and screen-reader passes**, because an automated pass is not an accessible interface |
| **performance targets** | interaction responsiveness, first meaningful render and bounded query time — set as targets for the implementation cycle to measure. **This cycle measures nothing and claims nothing** |

---

## 16. What this document does not do

```text
implements NOTHING                        authorizes NOTHING
builds no component                       creates no token file
installs no dependency                    deploys nothing
inspects no third-party design            claims no third-party stack
measures no performance                   claims no accessibility conformance
```

**Every acceptance criterion above is a target for a later, separately authorized implementation
cycle.** **Specification, implementation, research, deployment and execution are five separate
gates.**

```text
Cockpit interface implementation:        NOT STARTED / NOT AUTHORIZED
accessibility conformance:               NOT MEASURED / NOT CLAIMED
performance:                             NOT MEASURED / NOT CLAIMED
G1 / G2:                                 OPEN / OPEN
provider selected:                       NONE
Phase 3:                                 NOT COMPLETE
CONTROL:                                 DEFERRED
live trading:                            HARD-DISABLED
```
