# ADR-0006 — Adopt Blueprint V3.0 and Strategy Brain / Self-Maturation Governance

**Status:** **Accepted**
**Date:** 2026-08-27
**Supersedes:** the authority position of Blueprint V2.1 (the document itself is preserved)
**Superseded by:** —
**Relates to:** [ADR-0001](ADR-0001-system-foundation.md), [ADR-0002](ADR-0002-broker-adapter-and-brokerage-boundary.md), [ADR-0003](ADR-0003-broker-side-order-controls-are-not-safety-invariants.md), [ADR-0004](ADR-0004-deterministic-order-identity-idempotency-and-execution-lifecycle.md), [ADR-0005](ADR-0005-point-in-time-data-architecture.md)

---

## Context

Blueprint V2.1 has been the highest architecture authority since the repository was founded.
It carried Phase 1 (IBKR Paper connectivity) and Phase 2 (controlled Paper order lifecycle)
to accepted certification, and it framed the Phase 3 point-in-time planning package.

Since it was issued, four things matured past what it says:

1. **Empirical correction.** Broker-side order controls proved not to be safety invariants
   ([ADR-0003](ADR-0003-broker-side-order-controls-are-not-safety-invariants.md), indexed as
   errata E-001). V2.1 §25 assumed otherwise.
2. **Data architecture.** The Phase-3 planning package and
   [ADR-0005](ADR-0005-point-in-time-data-architecture.md) defined a vendor-neutral
   Bronze/Silver/Gold point-in-time platform with explicit information-set profiles that V2.1
   does not describe.
3. **Strategy structure.** Independent strategy review showed that naming Breakout, Pullback
   and PEAD as three independent engines overstates diversification, and that a short book
   built as a stricter mirror of the long book is not a short alpha.
4. **Governance.** The system is intended to improve itself. V2.1 has no vocabulary for what
   an improving system may do without a human, and what it may never do without one.

Blueprint V3.0 was drafted to close those four gaps, reviewed by the owner, and authorized for
formal adoption through a documentation-only pull request.

---

## Decision

**Adopt KalpaMani Blueprint V3.0 as the highest repository architecture authority.**

The adopted document is
[`docs/architecture/KalpaMani_Blueprint_V3_0.pdf`](../architecture/KalpaMani_Blueprint_V3_0.pdf)
— 17 pages, SHA-256
`2726b96dd69c8982788b1c2bd646ce7a52879c649994a31858dc41666761996d`.

### The document is adopted as issued, and is never edited

This repository already holds that **a Blueprint PDF is never edited**
([BLUEPRINT_ERRATA.md](../architecture/BLUEPRINT_ERRATA.md)): the document is the architecture
record *as issued*, its byte integrity is verifiable, and corrections are recorded in an ADR and
indexed beside it. V3.0 is adopted under that same rule.

Consequently, the adopted PDF's own Document Control page still reads as it did when it was
written for review — proposed status, a pre-merge main SHA, and an open PR #7. That page is
**superseded, not true**. The governing status of the document is this ADR and the
[adoption record](../architecture/BLUEPRINT_V3_ADOPTION.md), which carry the corrected Document
Control values in text, where they are auditable:

| Document Control field | As printed in the PDF (superseded) | **Governing value** |
|---|---|---|
| Status | proposed, owner review required | **ADOPTED / REPOSITORY AUTHORITY** |
| Supersedes | V2.1 only after formal repository adoption | **Blueprint V2.1, as highest architecture authority** |
| Repository main | `9ffeea2f57de1dec233937e1627d2acb27fb1051` | **Adoption base main `7e76cce22b98e78071076d04f43a29dc60b0d38c`** — *not* a permanent value |
| PR #7 | open / unmerged | **MERGED** (2026-08-27) |
| PR #7 final implementation | `6b680c03b85f21ce8d3703c1181c07a6e4bfa3bc` | **`6d33b11e52a875964c5b78b2f77685f4a73b7f45`** |
| Current project phase | A1 in review, not accepted | **Phase 3A A1 ACCEPTED; remaining Phase 3A — provider and real-data qualification** |
| ADR-0005 | Proposed | **Proposed — unchanged** |
| G1–G5 | Open | **Open — unchanged; G6 and G7 added** |

### When adoption takes effect

Owner approval and this ADR are recorded as of **2026-08-27**, but **repository authority
changes when the adoption artifacts land on `main`**. The adoption event is therefore:

| | |
|---|---|
| Owner approval date | 2026-08-27 |
| Adoption base main | `7e76cce22b98e78071076d04f43a29dc60b0d38c` — the commit PR #8 was branched from |
| Adoption PR | **#8** — *Adopt KalpaMani Blueprint V3.0* |
| **Effective adoption event** | **the merge of PR #8 into `main`** |

**Blueprint V3.0 becomes repository authority when PR #8 is merged into `main`.**

The adoption base main is **not** the permanent or current value of `main` after adoption.
Merging PR #8 necessarily advances `main`; the resulting main SHA is **repository state,
not an immutable architecture input**, and the blueprint's authority does not depend on it.
The final merge SHA and timestamp are **not predicted or hard-coded here** — for an open
pull request GitHub's pre-merge `merge_commit_sha` is provisional and is not adoption
evidence. They may be recorded in the post-merge closeout report without a further
documentation commit.

The alternative — rewriting the PDF's status page — was rejected. The document is produced from
subsetted fonts with absolutely positioned, non-reflowing text; no target string exists as a
literal in any content stream; and the changes span multi-line table cells plus a header and
footer on all 17 pages. Editing it would risk silently corrupting the architecture record and
would break the byte-identity that lets the owner prove the adopted file is exactly the file
that was reviewed.

---

## A. Supersession

- **Blueprint V3.0 supersedes Blueprint V2.1 for all future architecture decisions.**
- **Blueprint V2.1 is not deleted, moved or altered.** It remains at
  [`docs/architecture/KalpaMani_Blueprint_V2_1.pdf`](../architecture/KalpaMani_Blueprint_V2_1.pdf)
  (SHA-256 `3adaf59f01616c3b491ee988e2f60c43e863578edca74241c12b6b0b1c1495d2`) as **immutable
  historical evidence** of the architecture under which Phase 1, Phase 2 and the early Phase 3
  work were designed, executed and accepted.
- **Accepted Phase-1 and Phase-2 certification evidence remains valid.** It was earned under
  V2.1 and is not re-opened, re-scoped or re-certified by this adoption. The Phase-2 certified
  scope stays exactly as narrow as
  [its certification record](../certification/phase2-paper-order-lifecycle.md) states.
- **ADR-0001 through ADR-0005 stand.** Approved ADRs continue to govern where they refine or
  correct an operational assumption — including
  [ADR-0003](ADR-0003-broker-side-order-controls-are-not-safety-invariants.md), whose empirical
  finding survives the change of blueprint.
- **BLUEPRINT_ERRATA.md continues to apply to V2.1.** It corrects assumptions in the historical
  document; it is not retired by V3 adoption.

## B. Authority order

```
Blueprint V3.0
    ->  approved ADRs
    ->  CLAUDE.md
    ->  approved task specifications
    ->  implementation judgment
```

Higher wins. If a lower-level instruction appears to conflict with Blueprint V3.0, the conflict
is reported and proposed as an ADR — the system is not silently redesigned. Blueprint V2.1 is
**no longer in the authority order**; it is historical evidence.

## C. Self-maturing, not self-governing

The system **may** do the following automatically, within approved deterministic limits:

> monitor · diagnose · research · generate hypotheses · run approved backtests ·
> build challengers · shadow · reduce or disable unsafe new entries · fail closed

The system **may not** do any of the following automatically, ever:

> promote a strategy into order-producing Paper or live operation · increase capital ·
> increase risk · add leverage · expand short exposure · purchase a licence ·
> add a provider · resume a governed safety suspension

Those are **explicit human-authority decisions**. Automation may prepare, evidence and
recommend them; it may not take them. Emergency *reduction* of risk is automatic; emergency
flattening runs only under a preapproved independent kill-switch design, and the human always
retains direct control.

This does not weaken any existing rule. The deterministic/AI boundary is unchanged: AI may
process information and challenge theses; deterministic software controls money, risk and
broker actions.

## D. Strategy taxonomy

V3 makes six distinct concepts non-interchangeable:

| Term | Meaning |
|---|---|
| **Alpha family** | An economic reason a return exists. Carries the family risk budget and factor accounting. |
| **Strategy module / book** | A separately versioned, separately attributed implementation inside a family. |
| **Trade template** | A specific entry / invalidation / exit construction used by a module. |
| **Feature** | A measured input to ranking. Not a strategy. |
| **Filter** | An eligibility gate. Not a strategy. |
| **Risk overlay** | A constraint applied after candidate generation. Not a strategy. |

**Different labels do not constitute diversification.** Two modules that load on the same
factors are one exposure with two names, and are budgeted as one. Concretely: Momentum Breakout
and Momentum Pullback remain separately versioned and separately attributed modules, but they
share a **Momentum Continuation** family cap and factor-risk budget. PEAD remains a separate
**Event / Information Drift** family. A **Fundamental Deterioration Short** family is added,
because breakdown price action is *timing*, not sufficient short alpha.

Whether Breakout and Pullback are economically distinct enough to justify separate module
budgets within the family is **not decided here** — it is gate **G7**.

## E. Brain boundary

The future Strategy Brain terminates at **`CandidateIntent`**.

`CandidateIntent` **may** carry: identity and as-of time; family, module, template and version
pins; the factor vector, rank, setup quality and lineage; AI research and challenger output with
source timestamps, model version and prompt version; the trade thesis (entry condition,
invalidation condition, technical stop *reference*, expected holding period); risk context
(event flags, gap risk, liquidity, family / factor / sector exposure); short context (borrow
evidence, squeeze / SSR / recall constraints); and a typed decision status with deterministic
reasons.

`CandidateIntent` **may never** carry:

> shares · dollar size · broker order type · route · client order ID · broker order ID

Portfolio construction, risk, sizing, order approval and execution remain **deterministic
downstream layers**. No AI output and no Brain output crosses into them as an instruction. This
is the V2.1 locked principle expressed as a typed contract boundary, and it is unchanged in
substance.

## F. Data and licensing

- **QuantConnect LEAN remains the engine** for backtests and execution. It is already selected,
  used and certified against IBKR Paper.
- **IBKR Pro remains the broker, behind `BrokerAdapter`**
  ([ADR-0002](ADR-0002-broker-adapter-and-brokerage-boundary.md)).
- The **preferred historical point-in-time architecture is Sharadar + SEC EDGAR** — *preferred,
  not selected*. It is subject to **G1** (provider qualification, tests P1–P9) and **G3**
  (personal-use licence verification). Nothing is purchased, trialled or credentialed by this
  ADR.
- **QuantConnect local historical data is not automatically imported into KalpaMani
  Bronze/Silver/Gold.** Local-use restrictions and cost make it unsuitable as the primary
  point-in-time store. Cloud-contained experiments may be used later only where licensing
  permits, with no raw export.
- **Vendor payloads, vendor-derived normalized records, reconstructable derivatives, vendor
  quality reports and credentials stay outside Git**, under untracked runtime storage. Public
  code may describe interfaces and carry synthetic fixtures; it may never carry subscribed data.
- Budget policy is recorded as governance, not as authorization: a **USD 1,500/year base data
  budget**, conditionally expandable to **USD 5,000/year** for a qualified dataset with
  measurable incremental value, personal use and owner capital only. **Any actual spend remains
  a separate human authorization.**

## G. Open decision gates

The five gates from ADR-0005 remain **OPEN** and are **not** closed, narrowed or implied
resolved by this adoption:

| Gate | Question | Required before |
|---|---|---|
| **G1** | Provider selection — does the preferred historical stack pass P1–P9? | Credentialed production ingestion; Phase-3 acceptance |
| **G2** | Production information-set profile — which profile governs capital-informing research, per dataset? | Capital-informing backtests |
| **G3** | Licensing — do personal-use terms permit the intended own-account use, retained artifacts and public code? | Purchase, credentialing or fetch |
| **G4** | Analyst revisions — can genuine point-in-time revisions be obtained at acceptable cost and licence? | Revision-enhanced PEAD / deterioration strategies |
| **G5** | Borrow history — can historical availability and fees be qualified with adequate coverage and PIT behaviour? | Certified short backtests; short strategy promotion |

V3 adds two further gates, **OPEN** from creation:

| Gate | Question | Required before |
|---|---|---|
| **G6** | Options overlay — does daily options information improve out-of-sample risk / alpha after timing and licensing controls? | Any production influence from options data |
| **G7** | Strategy-taxonomy evidence — do Breakout and Pullback produce sufficiently distinct economics to justify separate module budgets within the Momentum Continuation family? | Later allocator and capital-budget decisions |

**G1–G7 are all OPEN.** **ADR-0005 remains Proposed.** Adopting V3 does not silently accept
ADR-0005, and no gate is resolved by a document being adopted.

## H. Non-authority effect

**This adoption grants no implementation authority whatsoever.**

Explicitly, ADR-0006 does **not** authorize:

> Phase 3A A2 or A3 · Phase 3B · Phase 3C · Phase 3D · Phase 4 Brain implementation ·
> strategy, scanner or factor implementation · portfolio or risk engine implementation ·
> AI Research or Challenger agent implementation · provider access, trial, purchase or
> credentialing · real external-data acquisition · short research · Paper expansion beyond
> the certified Phase-2 scope · micro-live · live trading · any capital change · leverage ·
> any broker activity

Each of those requires its **own** explicit written task authorization, per CLAUDE.md §8.
Blueprint V3.0 describes an architecture the project intends to build. **A described
architecture is not permission to build it.** No strategy is authorized because code exists, and
no phase is authorized because a document describes it.

Live trading remains **hard-disabled** (`LIVE_TRADING_HARD_DISABLED = True`), behind two
independent gates, with Gate 2 deliberately not implemented. Nothing in V3 changes that, and
nothing in V3 may be read as a route to changing it.

---

## Consequences

**Good.**

- One current architecture authority, matching what the project has actually learned.
- Self-maturation is bounded by an explicit written authority matrix instead of by assumption.
- The Brain's output boundary is a typed contract, so "AI cannot size or route" becomes
  checkable rather than aspirational.
- Diversification claims now require economic evidence (G7) rather than distinct names.
- Historical evidence is preserved intact; Phase-1/2 certifications need no rework.

**Costs, accepted.**

- The adopted PDF's Document Control page contradicts its own governing status. Mitigated by
  recording the corrected values here and in the adoption record, both of which outrank the
  page, and by the documentation audit asserting they stay consistent.
- Two more open gates (G6, G7) to carry and eventually close.
- README, CLAUDE.md and the documentation audit must be kept in step with V3 rather than V2.1.

**Neutral.**

- No source code, test, dependency or runtime configuration change. No network call, no provider
  contact, no broker action.

---

## Compliance

| Check | State |
|---|---|
| Source code changed | **none** |
| Dependencies changed | **none** |
| Runtime configuration changed | **none** |
| Broker activity | **none** |
| Provider activity | **none** |
| Credentials touched | **none** |
| Blueprint V2.1 preserved | **yes**, byte-identical |
| `LIVE_TRADING_HARD_DISABLED` | **True** |
| Repository visibility | **PUBLIC** (development); must return PRIVATE before micro-live or real money |
| INC-0002 | **OPEN** |
