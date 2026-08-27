# Blueprint V3.0 — Adoption Record and V2.1 → V3 Delta Index

This is the index, not the blueprint. The architecture itself is the 17-page PDF; this file
records **when it became authority, what it replaced, and what changed** — so the delta is
readable without re-reading the document, and so the parts of its Document Control page that
adoption made untrue are corrected in text.

| | |
|---|---|
| **Owner approval date** | 2026-08-27 |
| **Adopted document** | [`KalpaMani_Blueprint_V3_0.pdf`](KalpaMani_Blueprint_V3_0.pdf) — 17 pages |
| **Adopted SHA-256** | `2726b96dd69c8982788b1c2bd646ce7a52879c649994a31858dc41666761996d` |
| **Historical document** | [`KalpaMani_Blueprint_V2_1.pdf`](KalpaMani_Blueprint_V2_1.pdf) — preserved, unaltered |
| **Historical SHA-256** | `3adaf59f01616c3b491ee988e2f60c43e863578edca74241c12b6b0b1c1495d2` |
| **Governing ADR** | [ADR-0006](../decisions/ADR-0006-adopt-blueprint-v3-and-strategy-brain-governance.md) — **Accepted** |
| **Adoption PR** | **#8** — *Adopt KalpaMani Blueprint V3.0* |
| **Adoption base main** | `7e76cce22b98e78071076d04f43a29dc60b0d38c` — the commit PR #8 was branched from |
| **Effective adoption event** | **the merge of PR #8 into `main`** |

## PR #7 merge evidence

Blueprint V3.0 was drafted while Phase 3A A1 was still in review, and its Document Control page
was written against that state. A1 has since been accepted and merged.

| | |
|---|---|
| Pull request | **#7** — *Implement Phase 3A point-in-time foundation kernel* |
| State | **MERGED**, 2026-08-27 |
| Final implementation commit | `6d33b11e52a875964c5b78b2f77685f4a73b7f45` |
| Final head at merge | `6739643c79ab06f841ded2c70add4c6747039fdd` |
| Merge commit — became the adoption base main for PR #8 | `7e76cce22b98e78071076d04f43a29dc60b0d38c` |

---

## Document Control override

**The Blueprint PDF is never edited** — the rule this repository already applies to V2.1
([BLUEPRINT_ERRATA.md](BLUEPRINT_ERRATA.md)). V3.0 is adopted **exactly as issued and reviewed**,
byte-for-byte, so its SHA-256 proves the adopted file is the file the owner approved.

The consequence is that the PDF's page-2 Document Control table still describes the document's
pre-adoption state. **That table is superseded by the values below**, which are authoritative:

| Field | Printed in the PDF — **superseded** | **Governing value** |
|---|---|---|
| Status | proposed; owner review required | **ADOPTED / REPOSITORY AUTHORITY** |
| Supersedes | V2.1 only after formal repository adoption | **Blueprint V2.1, as highest architecture authority** |
| Current repository main | `9ffeea2f57de1dec233937e1627d2acb27fb1051` | **Adoption base main `7e76cce22b98e78071076d04f43a29dc60b0d38c`** — *not* a permanent value; see below |
| Current implementation | PR #7 open / unmerged | **PR #7 MERGED** |
| Current PR #7 head | `6b680c03b85f21ce8d3703c1181c07a6e4bfa3bc` | **final implementation `6d33b11e52a875964c5b78b2f77685f4a73b7f45`** |
| Current project phase | A1 in review, not accepted | **A1 ACCEPTED; remaining Phase 3A — provider and real-data qualification** |
| ADR-0005 | Proposed | **Proposed — unchanged** |
| Decision gates | G1–G5 open | **G1–G7 OPEN** |

### The main SHA is repository state, not an architecture input

`7e76cce22b98e78071076d04f43a29dc60b0d38c` is the **adoption base main** — the commit
PR #8 was branched from. It is **not** the permanent or current value of `main` after
adoption, and must never be recorded as one.

Merging PR #8 necessarily advances `main`. **The repository main SHA after adoption is the
commit that merges PR #8, and that is repository state, not an immutable architecture
input.** The blueprint's authority does not depend on it, and no document here pins it.

The final merge SHA and merge timestamp are **deliberately not recorded in advance**. For
an open pull request, GitHub's pre-merge `merge_commit_sha` is a provisional test-merge
value, not adoption evidence; it is not predicted or hard-coded. Those values may be
recorded in the post-merge closeout report, which requires no further documentation commit.

The same override applies to the running header and footer on all 17 pages, and to the cover
banner. Those describe the document's status at drafting time; the status is set by ADR-0006.

Why the page was not simply rewritten: the PDF uses subsetted fonts with absolutely positioned,
non-reflowing text. No target string exists as a literal in any content stream, the changes span
multi-line table cells, and the header and footer repeat on every page. Editing it would risk
silently corrupting the architecture record and would destroy the byte-identity that makes the
adopted file verifiable. See ADR-0006, *The document is adopted as issued*.

---

## Major governance deltas, V2.1 → V3

| # | V2.1 | V3.0 |
|---|---|---|
| 1 | Autonomy described operationally; no authority vocabulary for an improving system | **Self-maturing, not self-governing.** An explicit authority matrix: the system may monitor, diagnose, research, hypothesize, backtest, build challengers, shadow, reduce or disable unsafe new entries, and fail closed — automatically. It may never promote a strategy into order-producing Paper/live, increase capital or risk, add leverage, expand short exposure, buy a licence, add a provider, or resume a governed safety suspension. |
| 2 | "Strategy" used loosely across engines, features and filters | **Six non-interchangeable terms:** alpha family · strategy module/book · trade template · feature · filter · risk overlay. **Different labels do not constitute diversification.** |
| 3 | Breakout, Pullback and PEAD as three independent engines | **Momentum Continuation family** groups Breakout and Pullback under one factor-risk budget and family cap, while keeping them separately versioned and separately attributed. PEAD stays a separate **Event / Information Drift** family. |
| 4 | Short book as a stricter mirror of the long book | **Fundamental Deterioration Short** as its own family. Breakdown price action is *timing*, not sufficient short alpha; deterioration/event evidence plus negative relative/residual momentum plus mandatory borrow / squeeze / SSR / recall controls. |
| 5 | No typed boundary between research output and execution | **`CandidateIntent` boundary.** The Brain ends there. It may carry thesis, evidence, lineage, risk and short context — never shares, dollar size, order type, route, client order ID or broker order ID. |
| 6 | Per-strategy risk caps, then an allocator | **Family exposure caps and factor-overlap control** first; candidate consolidation before portfolio risk. A slow allocator only after substantial forward evidence — no performance-chasing. |
| 7 | Options positioning not V1 | Still not V1, and **no automated options trading**. Defined as a **future daily option-chain research and risk overlay** behind a new gate. |
| 8 | Data provider largely implicit in the engine | **Provider-budget governance:** USD 1,500/year base, conditionally up to USD 5,000/year for a qualified dataset with measurable incremental value, personal use only, with an explicit spending priority. Any actual spend is a separate human authorization. |
| 9 | Five open decision gates (ADR-0005) | **Two added: G6** options overlay, **G7** strategy-taxonomy evidence. **G1–G7 all OPEN.** |

## What did not change

These are unchanged by adoption, and V3 may not be read as loosening any of them:

| Rule | State |
|---|---|
| KalpaMani strategy capital | **USD 80,000, authoritative.** Broker-reported equity is observed for reconciliation and never participates in sizing. |
| Money, risk and broker actions | **Deterministic software only.** AI processes information and challenges theses; it never sizes, routes, approves or overrides. |
| Averaging down | **Never.** |
| Initial leverage | **None.** |
| Live trading | **HARD-DISABLED.** Two independent gates; Gate 2 deliberately not implemented; `LIVE_TRADING_HARD_DISABLED = True`. |
| Paper and live promotion | **Human-authorized.** No automatic promotion into an order-producing environment. |
| Repository visibility | **PUBLIC for development; must return PRIVATE** before micro-live, real money, or production broker credentials. |
| Broker-side order controls | **Not safety invariants** ([ADR-0003](../decisions/ADR-0003-broker-side-order-controls-are-not-safety-invariants.md), errata E-001). Unchanged by V3. |
| Phase-1 / Phase-2 certification evidence | **Valid and unchanged**, at exactly its certified scope. |
| Secrets, identifiers and vendor payloads | **Never in Git.** |

## What adoption did *not* authorize

Adopting V3 changed the authority order and nothing else. It grants **no** implementation
authority for Phase 3A A2/A3, Phase 3B/3C/3D, Phase 4 Brain, strategies, scanner or factors,
portfolio or risk, AI agents, provider access or purchase, real data acquisition, short
research, Paper expansion, micro-live, live, capital change, or leverage. Each needs its own
written authorization. See ADR-0006 §H.

**Phase 3 is not complete.** V3 adoption is a governance change, not a phase milestone.
