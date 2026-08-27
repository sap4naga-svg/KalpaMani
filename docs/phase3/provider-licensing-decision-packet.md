# Phase 3 — Provider and Licensing Decision Packet (G1 / G3)

**Status: EVIDENCE AND RECOMMENDATION. NO DECISION IS TAKEN HERE.**

**G1 remains OPEN. G3 remains OPEN. ADR-0005 remains PROPOSED.**
**Nothing has been purchased, trialled or credentialed. No vendor account exists. No API key
has been requested, generated, entered or stored. No vendor data has been retrieved.**

Research performed **2026-08-27** by public-web review of official provider, legal and
government documentation. Every provider claim carries a claim id resolving to
[provider-source-register.md](provider-source-register.md), section `R2` for this round.

> **Why this document may exist in a public repository.** The Sharadar Personal Use License
> §8 forbids publishing or disclosing conclusions about the *value, usability or fitness for
> purpose* of the **Services or the Services Data** (`PSR-SHD-086`). No Services Data has been
> obtained, so no testing or evaluation of it has occurred or could have. What follows
> evaluates **published terms, published prices and published documentation** — the same
> boundary [provider-evaluation.md](provider-evaluation.md) §5.2 and the source register's own
> licensing note already draw. That boundary narrows sharply the moment a subscription exists;
> §3.5 below states where.

---

## 1. Executive recommendation

### **B — NEED WRITTEN LICENSING CLARIFICATION FIRST**

Sharadar Direct plus SEC EDGAR **remains the right candidate stack** and no alternative
displaces it (§8). The obstacle is not fitness. It is that two clauses of the governing licence,
read in full for the first time this round, collide with architecture that
[ADR-0005](../decisions/ADR-0005-point-in-time-data-architecture.md) has already committed to —
and a third leaves the project's core permission resting on a sentence that is not in the
licence at all.

**The three findings that produce recommendation B:**

**1. §10 deletion is wider than the architecture assumed, and it ends reproducibility at
cancellation.** Round 1 recorded the obligation as "delete all copies of the Services Data"
(`PSR-SHD-061`). The full clause reads *"delete from all computer systems you own or operate
all copies of the Services Data (including downloads, bulk files, caches, and extracts), **all
data sets that contain, substantially copy, or could reproduce the Services Data or Sharadar
tables**"* (`PSR-SHD-083`). On a plain reading that is the bronze archive, the silver
normalisation, and every gold artifact from which vendor rows are recoverable — the whole
storage stack of [implementation-plan.md](implementation-plan.md) §1.1. A research manifest
whose contract is *"reruns to an identical result hash, or fails loudly naming the missing
input"* (acceptance criterion 14) would, thirty days after any cancellation, be permanently in
the second state. **That is a consequence to accept before purchase, not to discover after.**

**2. §8 confidentiality bars private disclosure, not merely publication — and this repository
is reviewed in public.** The clause bars fitness conclusions being *"published in any way...or
**provided or otherwise disclosed to any outside individual or entity**, without prior written
approval"* (`PSR-SHD-086`). Round 1 caught the publication limb and drew the right conclusion:
P1–P9 outputs stay under `.runtime/`. The disclosure limb goes further — it reaches a reviewer
on a pull request. Every provider test this phase runs produces exactly such a conclusion, and
the clause names *prior written approval* as the cure. **Asking for that approval is cheaper
than designing around its absence.**

**3. The permission KalpaMani actually needs is in an FAQ, under terms that may change
unilaterally.** *"Personal Use covers individuals using the data for their own purposes:
research, backtesting, and automated trading of their own account with no external clients or
money managed for others"* (`PSR-SHD-107`, re-verified verbatim). The Terms contain no
equivalent carve-out, §2 separately bars use *"for yourself as a professional"*
(`PSR-SHD-049`), and §18 — read for the first time this round — permits Sharadar to change any
term *"at any time and in its sole discretion"*, effective on posting, accepted by continued
use (`PSR-SHD-082`). The page carries no version or effective date (`PSR-SHD-089`), so an
amendment is not detectable. **The single most important permission in this stack is the least
durable evidence in it.**

### What recommendation B is not

It is **not** a finding that Sharadar is unsuitable, and **not** a reason to shop for another
vendor. §8 concludes that no alternative at a published personal-use price supplies as-reported
filing-date-indexed fundamentals with delisted coverage, corporate actions and prices under one
licence. The vendors that would resolve the deeper gaps — a genuine revision chronology, or
point-in-time consensus — are institutional and quote-only (`PSR-MISC-021`, `PSR-MISC-024`).
Switching costs more and buys less.

It is also **not** the same as "more research required" (category D). The public record is now
substantially exhausted on the material points: all eighteen licence sections were read, every
relevant documentation page was retrieved, and current pricing was obtained. What remains
unresolved (§4) cannot be resolved from public sources, by design — one question is about the
vendor's own internal data production (`PSR-SHD-098`), and the rest are questions only the
licensor can answer about its own licence.

### The sequencing this implies

```
[now]  packet reviewed  ->  owner decides whether to send the §4 clarification questions
          |
          v
   written answers received   (a decision point, not a formality: the answers may
          |                    change the architecture, the budget, or the vendor)
          v
   OPTIONAL free-sample precheck        <- separately authorized; costs $0; uses no
          |                                subscription and answers P1/P3/P4/P5 in part
          v
   G3 closed  ->  G1 closed  ->  A2 licensing  ->  A3 purchase  ->  Phase 3A A2 build
```

Each arrow is a governed step under CLAUDE.md §8. **This packet authorizes none of them.**

---

## 2. Current governance state

Restated from [CLAUDE.md](../../CLAUDE.md) §9 and
[ADR-0006](../decisions/ADR-0006-adopt-blueprint-v3-and-strategy-brain-governance.md), and
unchanged by this document.

| Item | State |
|---|---|
| Authority order | Blueprint V3.0 → approved ADRs → CLAUDE.md → approved task spec → implementation judgment |
| Phase 1 · Phase 2 | COMPLETE / ACCEPTED |
| Phase 3 planning · Phase 3A A1 | ACCEPTED / MERGED |
| **Phase 3 overall** | **NOT COMPLETE** |
| ADR-0005 | **PROPOSED** |
| ADR-0006 | ACCEPTED (2026-08-27) |
| **G1** provider selection | **OPEN** |
| **G2** production information-set profile | **OPEN** |
| **G3** vendor licensing | **OPEN** |
| **G4** analyst-estimate gap | **OPEN** |
| **G5** borrow-history qualification | **OPEN** |
| **G6** options overlay | **OPEN** |
| **G7** strategy-taxonomy evidence | **OPEN** |
| A2 / A3 · Phase 3B / 3C / 3D | NOT STARTED / NOT AUTHORIZED |
| Provider purchase · trial · credentials · external fetch | NOT AUTHORIZED |
| Live trading | HARD-DISABLED |

Two ordering constraints from ADR-0005 §770–777 govern everything below: **G3 (licensing,
authorization A2) precedes G1's purchase (authorization A3)**, and **G2 cannot be settled
before G1**, because `provider_available_time` is only obtainable for a provider already
chosen.

---

## 3. G3 — licensing evidence

Classification vocabulary, applied per question:

| | |
|---|---|
| **CONFIRMED** | controlling licence text states it |
| **PROBABLY PERMITTED** | supported by official vendor sources short of licence text, with no clause against |
| **AMBIGUOUS** | official sources point both ways, or the licence is silent on a question its own structure raises |
| **PROBABLY PROHIBITED** | no clause names it, but the natural reading of clauses that do apply forbids it |
| **PROHIBITED** | controlling licence text forbids it |
| **NOT FOUND** | no source addresses it at all |

All Sharadar rows below are the **Personal Use License** at `https://sharadar.com/terms`,
retrieved 2026-08-27. **The page shows no effective date or version** (`PSR-SHD-089`), so no
row here can be pinned to a licence revision — a defect of the source, recorded rather than
smoothed over. Quotations are model-mediated: the fetch tool summarised rather than reproducing
the page verbatim, so **a reviewer should open the URL and confirm any string before relying on
it in a compliance decision.**

### 3.A Personal use

| Question | Class | Controlling language | Interpretation | KalpaMani consequence | Confidence |
|---|---|---|---|---|---|
| One individual | **CONFIRMED** | §2 *"This License is granted solely to natural persons for personal use."* (`PSR-SHD-047`); §3 *"This License is not available to legal entities or institutions."* (`PSR-SHD-052`) | The licence is exclusive to a natural person and cannot be accepted on behalf of any organisation. | Fits today. **Breaks the moment KalpaMani is operated inside an LLC, trust or family partnership** — a structure change would void the licence regardless of whose money is at risk. | High |
| Personal research | **CONFIRMED** | FAQ: *"research, backtesting"* (`PSR-SHD-107`); no clause against | Research on own account is the paradigm case the licence is for. | Phase 3 research use is within scope. | High |
| **Own-capital automated trading** | **AMBIGUOUS** | FAQ: *"automated trading of their own account with no external clients or money managed for others"* (`PSR-SHD-107`). Against it: §2 bars use *"for yourself as a professional"* (`PSR-SHD-049`) in a list that is expressly *"without limitation"* (`PSR-SHD-050`); the Terms contain no own-account carve-out; §18 permits unilateral amendment (`PSR-SHD-082`). | The FAQ answers KalpaMani's exact question and answers it favourably. It is also the **only** source that does, it is not licence text, it is undated, and the licence it interprets may change without notice. §2's own list does not name trading one's own money as prohibited — it prohibits trading *"on behalf of others"* — so the Terms are silent rather than adverse. | **This is the question the whole stack rests on.** The task specification's own rule applies directly: do not rely on marketing FAQ language where binding terms remain ambiguous. Written clarification requested at §4 Q1. | Medium |
| No external clients | **CONFIRMED** | FAQ condition (`PSR-SHD-107`); §2 prohibits *"trading or investing on behalf of others"* (`PSR-SHD-050`) | A condition of the permission, not a restriction on it. | Satisfied and must stay satisfied. Managing any third party's money terminates the licence's applicability. | High |
| No redistribution | **CONFIRMED** | §4 *"You may not publish, disseminate, re-distribute or share the Services Data, or any part thereof, or any derivative data that allows reverse engineering."* (`PSR-SHD-087`) | Blanket. The final limb is new this round and extends the bar to reconstructable derivatives. | Already the operating rule: vendor payloads never enter Git ([implementation-plan.md](implementation-plan.md) §1.3). | High |

### 3.B Automated use

| Question | Class | Controlling language | Interpretation | KalpaMani consequence | Confidence |
|---|---|---|---|---|---|
| Local automated ingestion | **PROBABLY PERMITTED** | No licence clause addresses automation (`PSR-SHD-088`). Vendor sources: FAQ names *"automated trading"* (`PSR-SHD-107`); API docs say *"you **or your application** must provide an API key"* (`PSR-SHD-102`); bulk downloads are a documented product (`PSR-SHD-092`) | The vendor sells the mechanism, documents application-level access, and restricts none of it. Permission is inferred from the product, not granted by the licence. | Bronze ingestion as designed is supportable. It rests on inference, so it moves to CONFIRMED only via §4 Q2. | Medium-high |
| Automated research and backtests | **CONFIRMED** | FAQ names *"research, backtesting"* explicitly (`PSR-SHD-107`) | Directly stated. | Phase 3A/3B/3D research use is covered. | High |
| Programmatic API / database access | **PROBABLY PERMITTED** | §4 bars *"transfer or make available access ... to others"* (`PSR-SHD-087`) — sharing access, not using it. API key required and application access contemplated (`PSR-SHD-102`) | Using one's own key programmatically is the documented mechanism; only sharing the key is barred. | The client may be automated. **A key passed in the query string** (`PSR-SHD-102`) makes URL redaction in logs a build requirement under CLAUDE.md §4, not optional hardening. See §5.5. | Medium-high |
| Repeated scheduled retrieval | **AMBIGUOUS** | **No rate limit, quota, page-size or concurrency limit is documented anywhere** (`PSR-SHD-102`). The vendor documents `lastupdated.gte=` incremental sync as the intended update pattern (`PSR-SHD-093`) | Incremental scheduled sync is the pattern the vendor's own filter exists to serve. But an undocumented limit is not an absent limit, and §5 permits cancellation at sole discretion (`PSR-SHD-081`). | A nightly refresh is very likely fine; a wide historical backfill has **no stated budget to plan against**, so backfill wall-clock and courtesy pacing cannot be designed from public sources. §4 Q3. | Medium |

### 3.C Retention after expiry or termination

**The adverse finding of this round, and the one with architectural consequences.**

| Artifact | Class | Controlling language | KalpaMani consequence | Confidence |
|---|---|---|---|---|
| Raw downloaded data | **PROHIBITED** | §10: delete within 30 days *"all copies of the Services Data (including downloads, bulk files, caches, and extracts)"* (`PSR-SHD-083`) | The **bronze layer must be destroyed** 30 days after termination. Bronze is the append-only immutable record on which backfill detection and every reproducibility guarantee rests. | High |
| Normalized records | **PROHIBITED** | §10: *"all data sets that contain, substantially copy, or could reproduce the Services Data or Sharadar tables"* (`PSR-SHD-083`) | The **silver layer is squarely inside this**, being a normalisation of vendor rows. So is any gold artifact from which vendor rows are recoverable. | High |
| Historical snapshots | **PROHIBITED** | Same clause; "extracts" and "could reproduce" both reach them | A point-in-time archive **cannot be a durable asset**. Its lifetime is the subscription's. | High |
| Derived research artifacts | **PROBABLY PERMITTED**, boundary **AMBIGUOUS** | §10 carve-out: *"You may keep research outputs, backtest results, models, summary statistics, trade logs, and similar derived works that do not contain and cannot reproduce the Services Data or Sharadar tables."* (`PSR-SHD-084`) | Real and useful, but the test is **reconstructability, not how derived a thing feels**. A scalar performance summary passes easily. A per-security per-date factor panel is much closer to the line and is not addressed. §4 Q4. | Medium |
| Backtest **inputs** | **PROHIBITED** | The inputs are the Services Data | A manifest can survive; **the data it names cannot**. | High |
| Backtest **results** | **PROBABLY PERMITTED** | §10 names *"backtest results"* in the carve-out (`PSR-SHD-084`) | Results are keepable. Whether they are *publishable* is a different clause — §3.E. | Medium-high |
| Backups | **PROHIBITED** | §10 reaches *"all computer systems you own or operate"* and *"all copies"* (`PSR-SHD-083`) | Backups and cold storage are covered. Any retention design must be able to prove deletion, not merely intend it. | Medium-high |

> **The consequence, stated once and plainly.** ADR-0005's reproducibility model and Phase 3
> acceptance criterion 14 promise that a research manifest reruns to an identical result hash.
> **Under §10 that promise expires 30 days after the subscription does.** This is not a defect
> in the vendor and not a defect in the architecture; it is a property of renting data rather
> than owning it, and it is true of every low-cost provider examined. It must be **accepted
> explicitly by the owner and declared in the manifest model**, not discovered later. Note the
> asymmetry that makes it sharper: §10 permits Sharadar to terminate *"without prior notice"*
> (`PSR-SHD-085`), so the 30-day clock can start unannounced.

### 3.D Derived data

The licence does **not** draw the taxonomy this question assumes. There is no distinction in the
text among model outputs, factor values, research results and transformed vendor records. There
is **one binary test**, expressed twice:

| Where | Test |
|---|---|
| §4, redistribution | does it *"allow reverse engineering"* of the data? (`PSR-SHD-087`) |
| §10, retention | does it *"contain, substantially copy, or could reproduce the Services Data or Sharadar tables"*? (`PSR-SHD-083`, `PSR-SHD-084`) |

Both ask the same thing: **can the vendor's rows be recovered from the artifact?**

| Category | Retain | Publish / redistribute | Note |
|---|---|---|---|
| Non-reconstructable derived statistics | **PROBABLY PERMITTED** | **PROBABLY PERMITTED**, unless it is a fitness conclusion — then §8 applies | The §8 overlay is the trap; see §3.E |
| Model outputs, research results, backtest results | **PROBABLY PERMITTED** — named in the §10 carve-out | **AMBIGUOUS** — §10 grants retention, not publication; §2 lists *"publication"* among prohibited professional uses (`PSR-SHD-050`) | Retention and publication are different grants |
| Factor values (per security, per date) | **AMBIGUOUS** | **AMBIGUOUS** | A dense panel keyed like the source is the hardest case under "could reproduce". §4 Q4 |
| Transformed / normalized vendor records | **PROHIBITED** | **PROHIBITED** | This is *"substantially copy"* by construction — it is the silver layer |
| Reconstructable derivatives | **PROHIBITED** | **PROHIBITED** | Both clauses reach it explicitly |

> **§6 attribution is not a publication licence.** §6 requires *"Data from Sharadar.com"*
> attribution where data is publicly displayed, and states attribution is *not* required for
> *"research outputs, backtest results, models, summary statistics, trade logs"*
> (`PSR-SHD-057`, `PSR-SHD-058`). Round 1 already warned against misreading this, and the
> warning stands: §6 governs **how** permitted display is labelled. §4 governs **whether**
> anything may be published at all, and §8 governs evaluations. Reading §6 as a grant would
> invert the licence.

### 3.E Public GitHub

The repository is **PUBLIC for development** (CLAUDE.md §3) and is reviewed through pull
requests. Both facts matter here.

| Artifact | Class | Basis |
|---|---|---|
| Public source code | **CONFIRMED** permitted | No clause touches code. The licence governs data, not software written to read it. |
| Public schemas / field mappings | **PROBABLY PERMITTED** | Column names and types are metadata describing the product, published by the vendor itself. §4 bars the *Services Data*. **But** a schema annotated with quality conclusions crosses into §8. |
| Synthetic fixtures | **CONFIRMED** permitted | Invented data is not Services Data. This is exactly what A1 already does, and why A1 was safe to merge. |
| Tests using invented data | **CONFIRMED** permitted | Same basis. |
| Vendor payloads, actual rows, reconstructable vendor-derived records | **PROHIBITED** | §4 (`PSR-SHD-087`), §10 (`PSR-SHD-083`). Unchanged and non-negotiable. |
| **Provider-test results, data-quality reports, cross-provider reconciliation output** | **PROHIBITED without prior written approval** | §8 (`PSR-SHD-086`) |

> **The §8 finding that changed this round.** Round 1 read §8 as a bar on *publication* and
> concluded that P1–P9 outputs stay under `.runtime/`. The full clause bars those conclusions
> being *"published in any way...**or provided or otherwise disclosed to any outside individual
> or entity**"* (`PSR-SHD-086`). Keeping a quality report out of Git does not, by itself,
> satisfy the disclosure limb — **showing it to a reviewer is a disclosure to an outside
> individual.** For a project whose entire review model is pull requests, and whose repository
> is public precisely to enable review, that is a real constraint on how provider qualification
> can be conducted. §8 names *prior written approval* as the cure, which is why §4 Q5 asks for
> it rather than designing around it.

**This document is not caught by §8.** No Services Data exists to have been tested or evaluated.
Every conclusion here concerns published terms, published prices and published documentation.

### 3.F AI / LLM use

| Question | Class |
|---|---|
| Do the terms address submitting vendor data to third-party LLM APIs? | **NOT FOUND** |
| Do they address machine learning or model training? | **NOT FOUND** |
| Do they address automated analysis? | **NOT FOUND** |

**No section of the Personal Use License mentions** artificial intelligence, machine learning,
large language models, model training, or transmission to a third-party service
(`PSR-SHD-088`). A targeted search for AI clauses in comparable financial-data vendor terms
surfaced no vendor-specific language for any candidate in this stack.

**Silence is not permission, and the clauses that do exist point the other way.** Sending
Sharadar rows to a third-party LLM API would be *making the data available to others* (§4,
`PSR-SHD-087`) and, where the prompt asks the model to assess the data, *disclosing a fitness
conclusion to an outside entity* (§8, `PSR-SHD-086`). On the natural reading of clauses that do
apply: **PROBABLY PROHIBITED.**

> **Architectural consequence, and it is a clean one.** Blueprint V3.0 confines AI to
> qualitative information processing — filings, news, thesis challenge — while deterministic
> software owns everything quantitative. That boundary happens to also be the licensing-safe
> boundary: **SEC filings are public-domain and may be sent to an AI layer; subscribed vendor
> rows must not be.** Recommended rule, to be recorded when the AI layer is designed rather
> than asserted here: *no Sharadar-sourced record may enter an AI prompt.* It costs the design
> nothing, because the AI layer was never meant to see quantitative vendor data. §4 Q6 asks the
> vendor to confirm.

### 3.G Termination and cancellation

| Question | Answer | Source |
|---|---|---|
| What must be deleted? | All copies of the data, including downloads, bulk files, caches and extracts; all datasets that contain, substantially copy or could reproduce the data or the vendor's tables; all supplied software. Within **30 days**. | `PSR-SHD-083` |
| What may remain? | Research outputs, backtest results, models, summary statistics, trade logs and similar derived works **that cannot reproduce** the data or tables. | `PSR-SHD-084` |
| Must backups be removed? | The clause reaches *"all computer systems you own or operate"* and *"all copies"*. **Yes**, on the natural reading. Backups are not separately addressed. | `PSR-SHD-083` |
| Does derived research survive? | Yes, subject to the reconstructability test — whose boundary is undefined. | `PSR-SHD-084` |
| Refunds | Subscriber cancellation: no refund of money already paid (§9, `PSR-SHD-045`). Vendor termination **without cause**: pro-rata refund of prepaid fees. Vendor termination **for cause**: no refund (§5, §10). | `PSR-SHD-045`, `PSR-SHD-081`, `PSR-SHD-085` |
| Can termination be immediate? | Yes — *"without prior notice, immediately terminate, limit, or suspend your access"*. | `PSR-SHD-085` |

### 3.H Commercial / non-commercial classification

**Is trading only the owner's own capital treated as personal/non-commercial? — AMBIGUOUS.**

| Evidence | Direction | Grade |
|---|---|---|
| FAQ: *"automated trading of their own account with no external clients or money managed for others"* (`PSR-SHD-107`) | **For** | `V` — official, but an undated FAQ, not licence text |
| §2 prohibited list names *"trading or investing **on behalf of others**"* — not trading one's own money (`PSR-SHD-050`) | **For** — by omission | `V` |
| §2 bars use *"for yourself as a professional"* (`PSR-SHD-049`), in a list expressly *"without limitation"* | **Against** | `V` |
| §5: Sharadar *"may request reasonable proof that you are using this License appropriately"*, enforced by cancellation without refund at sole discretion (`PSR-SHD-081`) | **Against** — the classification is the licensor's to apply | `V` |
| §18: terms may change unilaterally, effective on posting, accepted by continued use (`PSR-SHD-082`) | **Against** — no permission here is durable | `V` |
| Reseller test: professional licence required if you manage others' money, work in finance, are compensated for analysis, operate as a business, **or collaborate with others** (`PSR-SHD-069`) | **Against**, and stricter than the vendor's own FAQ | `V2` — a reseller's rendering of its own agreement; not the governing wording |

**Applying the task's own rule** — do not rely on marketing FAQ language where binding terms
conflict or remain ambiguous — the classification is **AMBIGUOUS**, and it is the reason this
packet returns category B rather than A.

Two forward-looking notes, neither of which is a decision:

- **"Collaborate with others" versus a public repository.** `PSR-SHD-069` is `V2` and is a
  reseller's paraphrase, so it is a warning about how the professional test is applied
  downstream, not the governing wording. It is still uncomfortable next to a repository that is
  public *for collaboration* (CLAUDE.md §3). Worth resolving before, not after, someone
  contributes.
- **Micro-live and any entity structure.** CLAUDE.md §3 requires the repository to return to
  private before micro-live or real money. §3 of the licence separately voids it for any entity
  (`PSR-SHD-052`). If KalpaMani is ever operated through an LLC or trust, the licence must
  change at the same moment — and the commercial channel's terms **cannot be assessed from
  public sources at all** (`PSR-MISC-023`).

### 3.I SEC EDGAR

| Question | Class | Evidence |
|---|---|---|
| Public-access status | **CONFIRMED** free public access; public-domain content `V2` | `PSR-SEC-001`, `PSR-SEC-002` — unchanged, and **not re-verifiable this round** because no sec.gov page could be read |
| Fair-access / automated-access requirements exist | **CONFIRMED** | `PSR-SEC-045` — SEC-served text, retrieved today: *"Automated access to our sites must comply with SEC.gov's Privacy and Security Policy. Please visit www.sec.gov/developer for more developer resources and Fair Access guidelines."* |
| Rate limit and identification parameters | **PROBABLY PERMITTED** at stated parameters, `V2` only | `PSR-SEC-046` — declared User-Agent carrying contact information; no more than 10 requests/second per requester; 403 and a temporary IP block otherwise |
| Redistribution | **PROBABLY PERMITTED**, `V2` | Public-domain content (`PSR-SEC-001`), subject to a **branding** carve-out: the SEC seal, logos and the EDGAR trademarks may not be reused (`PSR-SEC-047`). A branding restriction, not a content restriction. |
| **Does any licence issue materially block KalpaMani's intended use?** | **NO** | Filing content is public-domain, free, and carries acceptance timestamps — the property that makes EDGAR the only route to `AS_KNOWN_AT_AS_OF`. There is no licence obstacle. |

**Two operational cautions, neither of them a licensing problem:**

1. **sec.gov is unreachable from this environment, for the second consecutive round.** Six URLs
   were attempted today — three by fetch tool, three by plain HTTP client with a descriptive
   User-Agent — and all six returned a page the SEC serves titled *"Request Rate Threshold
   Exceeded"* (`PSR-SEC-045`). That identifies the block as a **rate-threshold response**, not
   an authorization denial, which is consistent with a shared or reputation-flagged egress
   address and says nothing about this project. The Internet Archive route is also closed
   (`PSR-SEC-048`). **Consequence: every EDGAR field-level claim remains `V2`, and the exact
   required User-Agent format remains unestablished.** Verifying it is Phase-3B work, from an
   environment that can reach sec.gov.
2. **The User-Agent contact string is an identity decision the owner must make.** Fair access
   requires a real contact. Which address KalpaMani declares is a Phase-3B choice with a small
   privacy dimension, and it is **not made here**. No personal address was sent to sec.gov in
   this round.

---

## 4. Open licensing questions

Six questions that public sources cannot answer, drafted at
[provider-licensing-clarification-draft.md](provider-licensing-clarification-draft.md).

**That draft has not been sent. No support ticket has been opened. No email has been sent.
Sending it is an owner decision.**

| # | Question | Why public evidence cannot settle it | Blocks |
|---|---|---|---|
| **Q1** | Does the Personal Use License cover a single individual running an automated system that trades **only their own capital**, with no clients and no money managed for others — and does the FAQ statement bind? | The only affirmative source is an undated FAQ; the Terms neither repeat nor contradict it; §18 permits unilateral amendment. Only the licensor can say whether the FAQ binds. | **A3 purchase.** Everything downstream. |
| **Q2** | Is **automated programmatic retrieval** — scheduled incremental sync and an initial historical backfill — within scope? | The licence is silent (`PSR-SHD-088`); permission is inferred from the product's existence. | Bronze ingestion design |
| **Q3** | Are there **rate limits, request quotas or fair-use expectations** for the API and bulk downloads? | Documented nowhere (`PSR-SHD-102`, `PSR-SHD-105`). | Backfill pacing; wall-clock estimates |
| **Q4** | Under §10, may a **normalized local store** and **derived point-in-time research artifacts** be retained after cancellation, and where is the line for "could reproduce"? | §10's reproduction test is undefined in the text; the answer decides whether reproducibility survives cancellation. | **The reproducibility architecture.** ADR-0005 acceptance |
| **Q5** | Under §8, may **empirical data-quality findings** be disclosed to reviewers and published in a public repository — and will written approval be granted? | §8 requires *prior written approval* and names no request process. | How P1–P9 evidence is reviewed and retained |
| **Q6** | May Services Data be **submitted to third-party AI/LLM services** for analysis? | Not addressed anywhere (`PSR-SHD-088`). | The Blueprint AI layer's data boundary |

**A seventh question is not for the licensor but is equally blocking**, and it is a data-fitness
question rather than a licensing one — see P9 in §6:

| # | Question | Why |
|---|---|---|
| **Q7** | Are Sharadar's daily bars **officially disseminated**, **provider-aggregated**, or otherwise constructed? | Not stated in the documentation (`PSR-SHD-098`), and **not discoverable from the data**. If provider-aggregated, `price_bar` and everything derived from it — the universe included — is ineligible under `PUBLIC_PIT`. |

---

## 5. G1 — provider-fit assessment

**Not an execution of P1–P9.** No credential exists and no vendor data has been fetched. This is
what public documentation supports, per domain, with each item classified by what kind of thing
it would be.

### 5.1 Domain fit

| # | Domain | Support | Kind | Evidence |
|---|---|---|---|---|
| A | Security master / identifiers | **likely available** | vendor fact | `permaticker` is *"a unique and unchanging identifier for an issuer"* (`PSR-SHD-096`). Internal `security_id` still keys the system; no licensed identifier is required. |
| A′ | **Ticker history** | **partially available** | **KalpaMani-derived artifact** | **Adverse and new.** TICKERS holds the **current** symbol, not a date-ranged mapping (`PSR-SHD-096`). ACTIONS carries dated **ticker-change** events (`PSR-SHD-095`). Ticker-at-a-date is therefore **constructed by us from a change log**, not supplied. See §5.3. |
| A″ | Delistings | **likely available** | vendor fact | `isdelisted` flag (`PSR-SHD-096`); ACTIONS carries delisting dates and delist reasons (`PSR-SHD-095`); prices cover *"active and delisted US public stocks"* (`PSR-SHD-099`). **Claimed, not audited — that is P2.** |
| B | Historical universe membership | **not sold by anyone** | **KalpaMani-derived artifact** | Unchanged: membership is constructed from A + D + F under the Blueprint §4 rule. |
| C | Market calendar | **likely available**, free | derived / open source | LEAN `market-hours-database` authoritative; `exchange_calendars` as cross-check. Unchanged. |
| D | Historical daily prices | **likely available** | vendor fact | January 1998, ~21,000 current tickers, active and delisted (`PSR-SHD-099`). Raw **and** adjusted supplied (`PSR-SHD-097`). |
| D′ | **Bar construction / origin** | **unclear** | **unresolved** | Not stated (`PSR-SHD-098`). **This is P9 and its failure mode is the largest in the set.** |
| E | Corporate actions | **partially available** | vendor fact | Splits, dividends, spinoffs, ticker changes, ADR ratios, listings, delistings, acquisition counterparties, from January 1998 (`PSR-SHD-095`). **No announcement date** (`PSR-SHD-094`) — see §5.2. Per-action field semantics undocumented. |
| F | Exchange / listing information | **likely available** | vendor fact | Nasdaq, NYSE, NYSEMKT common stock, primary class (`PSR-SHD-101`). |
| G | Fundamentals (as-reported) | **likely available** | vendor fact | AR dimensions *"time-indexed to the date of the form 10 regulatory filing to the SEC"*, excluding restatements; ~18,000 active and delisted companies, deep history to 1998 (`PSR-SHD-101`). |
| G′ | **Data revisions / restatements** | **apparently unavailable** as a chronology | vendor limitation | Two-view model only: AR excludes restatements, MR is updated **in place** and indexed to the report period (`PSR-SHD-101`). `AS_KNOWN_AT_AS_OF` is **not** achievable from Sharadar alone. Unchanged from round 1 (`PSR-SHD-079`) and re-verified. |
| H | Filings | **likely available**, free | **public SEC fact** | EDGAR. The only source of acceptance timestamps, hence the only route to `AS_KNOWN_AT_AS_OF`. Access unverified from this environment (`PSR-SEC-045`). |
| I | Earnings events | **partially available** | vendor fact + public SEC fact | EVENTS is 8-K-derived, **date only, no time**, from January 2004 (`PSR-SHD-100`). Timing must come from EDGAR 8-K acceptance times; `EARNINGS_TIME_APPROXIMATED` applies either way. |
| I′ | Earnings dates / timestamps | **partially available** | public SEC fact | As above. A conservative approximation that can delay but never advance information — the safe direction. |
| J | Guidance | **apparently unavailable** | — | No guidance product identified at a personal-use price. |
| K | Analyst estimates / revisions | **apparently unavailable** | — | Unchanged and corroborated from a new angle: the vendors with genuine per-revision availability are institutional and quote-only (`PSR-MISC-021`, `PSR-MISC-024`). **G4 stays open** — §9. |
| L | Historical availability semantics | **partially available**, **bounded** | vendor limitation | `lastupdated` reads as *last changed*, for incremental sync (`PSR-SHD-093`), and is a **date**. So `provider_available_time` is unobtainable exactly and the `BOUND` resolution applies. **This is P1, and the documentation points at the answer the plan already predicted.** |
| M | Borrow | **apparently unavailable** from this stack | — | Not a price/fundamental vendor's product. **G5 stays open and separate** — §9. |

### 5.2 P3 is answered by public documentation, and the answer is adverse

The ACTIONS table has seven columns and **no announcement or declaration date distinct from the
effective date** (`PSR-SHD-094`). Round 1 recorded this as *"unresolved — validate in 3A"*; the
vendor's own column list resolves it without a subscription.

**Consequence:** the [contract §9](pit-data-contract.md) lag applies and
`CORPORATE_ACTION_ANNOUNCE_APPROXIMATED` is declared on every dependent result. This is
survivable — the contract has the token precisely for this — but it is now a **known** cost of
the stack rather than a risk to be tested, and it should be priced into the decision as such.

One caveat keeps P3 from being fully closed on documentation alone: the page does not state what
the single `date` column *means* per action type either (`PSR-SHD-095`). Whether it is the
ex-date, the effective date or something else still needs confirming against data.

### 5.3 Ticker history is a derived artifact, and that is the finding of §5

Round 1 recorded *"tickers table is time-structured — verify in 3A"* (`PSR-SHD-026`). On the
vendor's documented schema it is not: TICKERS carries the current symbol plus a permanent
issuer id (`PSR-SHD-096`).

This is structurally the **same shape that disqualified Norgate** as a security master
(`PSR-NRG-012`) — with one decisive difference:

| | Norgate | Sharadar |
|---|---|---|
| Historical ticker mapping supplied | **no** | **no** |
| Stable internal identifier | yes (`assetid`) | yes (`permaticker`) |
| **Dated change log from which history is reconstructable** | **no** | **yes** — ACTIONS ticker-change events (`PSR-SHD-095`) |

So Sharadar is **not** disqualified, and the conclusion of round 1 stands. But three things
change, and each is real work:

1. **Ticker-at-a-date becomes a `DERIVED_ARTIFACT`**, with its own lineage, its own availability
   under each profile, and its own eligibility — not a vendor fact carried through silver.
2. **Phase 3 acceptance criterion 1** — resolving a known ticker reassignment before and after
   the change — is now a test of *our* reconstruction as much as of the vendor's data. The
   contract's derived-artifact rules (fixtures N11, F24, F25) govern it.
3. **Correctness depends on undocumented semantics.** Whether `contraticker` holds the old or
   the new symbol on a ticker-change row is not documented (`PSR-SHD-095`), and getting it
   backwards inverts every historical mapping. Exactly the class of defect ADR-0004 §20
   describes: a sign convention assumed rather than observed, invisible behind green tests.

**Effort consequence:** the implementation-plan §8 estimate of 2–3.5 weeks for stage 3A did not
include building and validating a ticker-history derivation. It should be revised when 3A is
authorized. **This packet does not revise it.**

### 5.4 Current data is not point-in-time history — where that bites here

Stated as a standing caution, applied to what this round found:

- `isdelisted` is a **current** flag, and *"Current count of 21,000 tickers"* is a current
  count (`PSR-SHD-096`, `PSR-SHD-099`). Neither describes what was true at a past date.
- MR fundamentals are updated **in place** (`PSR-SHD-101`). They are current-restated values,
  not history, which is why research may never reach `LATEST_RESTATED`.
- The TICKERS row is a current row. Everything historical about identity is derived (§5.3).
- `lastupdated` moves when a row changes (`PSR-SHD-093`), so it describes the present state of
  a record and not when the record first appeared.

### 5.5 A security finding that is not about licensing

The API key is passed as a **query-string parameter** (`PSR-SHD-102`). URLs reach process
listings, shell history, HTTP client debug logs, proxy logs and exception traces. CLAUDE.md §4
forbids printing, storing, logging or committing credentials, and CLAUDE.md §3 makes any leak
world-readable while the repository is public.

**Consequence for whenever A3 is granted:** query-string redaction in every logging and
error path is a **build requirement of the provider client**, and a preflight check for it
belongs with the others. Recorded here so it is not discovered during implementation.

---

## 6. P1–P9 qualification plan

The nine tests are reproduced **verbatim** from
[implementation-plan.md](implementation-plan.md) §2 and §3 — the authoritative text. Nothing is
restated from memory and no criterion is invented.

### 6.0 A classification the plan does not currently draw

The task asks each test to be separated into `PUBLIC-DOC PRECHECK`, `CREDENTIALLED TEST` or
`PURCHASE-DEPENDENT TEST`. **P9 fits none of the three, and this is flagged rather than
forced.**

P9 asks whether daily bars are *officially disseminated, provider-aggregated, or resampled by
us*. That is a fact about the vendor's **production process**, not about its data. No sample of
bars exhibits it, so no amount of credentialed access or purchase answers it. The documentation
does not state it (`PSR-SHD-098`). **P9 is a vendor-clarification test** — a fourth class — and
it is carried as Q7 in §4.

This matters because P9 is the single largest failure mode in the set: a `PROVIDER_AGGREGATED`
answer makes `price_bar` — **and the universe built on it** — ineligible under `PUBLIC_PIT`.
Discovering that after purchase would be an expensive way to learn it.

A second, milder classification note: a subset of the tests can be **partially** exercised on
the free 30-name, 5-year sample (`PSR-SHD-103`) before any purchase. That is a genuine
cost reduction and is recorded in the matrix. **It is not free of governance** — the sample is
Services Data under the same Terms, and reading it is vendor-data retrieval requiring its own
authorization. It was not exercised in this round.

### 6.1 The matrix

| | P1 |
|---|---|
| **Test (verbatim)** | **Provider-availability semantics and origin.** Does the vendor update/`lastupdated` column mean "first appeared" or "last changed"? Verify against a row known to have changed. Record the dataset `information_origin` at the same time. |
| **Objective** | Establish whether `provider_available_time` is obtainable exactly, and fix each dataset's gap policy. |
| **Class** | **PUBLIC-DOC PRECHECK** (indicative) → **CREDENTIALLED TEST** (confirming) |
| **Evidence needed** | A row observed at two ingestions with a changed `lastupdated`, proving the column moves on change rather than staying at first appearance. |
| **Dataset / endpoint** | SF1 fundamentals; `lastupdated.gte=` filter (`PSR-SHD-093`) |
| **Smallest sample** | One security, two ingestions separated by a real vendor update. **Requires elapsed calendar time, not volume.** |
| **Pass condition** | Semantics determined and recorded, with `information_origin` set per dataset. |
| **Blocking failure** | Semantics indeterminate → no defensible gap policy can be declared. |
| **Credentials** | Yes for confirmation. Sample tier sufficient (`PSR-SHD-103`). |
| **Paid access** | No |
| **`.runtime/` artifact** | Two dated raw payloads for the same key, the observed diff, the derived semantics conclusion |
| **Committable** | The chosen gap policy per dataset and its rationale in configuration. **Not** the observed rows or the fitness conclusion (§3.E). |
| **Public-doc status now** | `lastupdated` is described as *"the last date that this database entry was updated"*, for incremental local sync (`PSR-SHD-093`) — i.e. **last changed**. It is also a **date**, so even bounded it is day-resolution. **`BOUND` is the expected outcome**, which is the safe one: it pins provider availability to first sight, so a vendor backfill cannot become historically admissible. |

| | P2 |
|---|---|
| **Test (verbatim)** | **Delisted coverage is real.** Sample securities delisted 5, 10 and 15 years ago and confirm full history is present. |
| **Objective** | Prove the survivorship control has something to stand on. |
| **Class** | **PURCHASE-DEPENDENT TEST** |
| **Evidence needed** | Named securities delisted ~2021, ~2016 and ~2011, each with price history through to its delisting and a delisting action. |
| **Dataset / endpoint** | TICKERS (`isdelisted`), SEP, ACTIONS |
| **Smallest sample** | Three securities per era, nine total, chosen from an independent list so the vendor's own coverage does not select the sample. |
| **Pass condition** | Full history present for all nine, consistent with the era. |
| **Blocking failure** | Any era materially empty → the survivorship control fails and the domain reverts to another source. Phase 3 acceptance criterion 2 states zero delisted members **fails**. |
| **Credentials** | Yes |
| **Paid access** | **Yes — and specifically the Full History tier.** A 15-year-old delisting is unreachable on the 5-year and 10-year tiers (`PSR-SHD-090`). |
| **`.runtime/` artifact** | The nine security ids, coverage spans observed, gaps found |
| **Committable** | Nothing. This is the paradigm §8 fitness conclusion. |
| **Note** | **Not runnable on the free sample**: 30 current DJIA constituents, 5 years (`PSR-SHD-103`). This test is the clearest reason the Full History tier is the only purchasable option. |

| | P3 |
|---|---|
| **Test (verbatim)** | **Corporate-action announcement timing.** Does the dataset carry an announcement date/time distinct from ex-date? |
| **Objective** | Decide whether `CORPORATE_ACTION_ANNOUNCE_APPROXIMATED` is declared. |
| **Class** | **PUBLIC-DOC PRECHECK — effectively answered** |
| **Evidence needed** | The ACTIONS column list. |
| **Dataset / endpoint** | ACTIONS |
| **Smallest sample** | None — schema-level. |
| **Pass condition** | An announcement/declaration column exists distinct from the effective date. |
| **Blocking failure** | Not blocking. The contract §9 lag applies and the token is declared. |
| **Credentials** | No |
| **Paid access** | No |
| **`.runtime/` artifact** | None required |
| **Committable** | The declared lag and token, as configuration |
| **Public-doc status now** | **Answered, adverse.** Seven columns, one `date`, no announcement or declaration date (`PSR-SHD-094`). What remains is confirming what the single `date` means per action type, which is undocumented (`PSR-SHD-095`) and needs data. |

| | P4 |
|---|---|
| **Test (verbatim)** | **Classification history.** Are sector/industry changes historised, or is only the current value supplied? |
| **Objective** | Decide whether `CLASSIFICATION_STATIC` applies. |
| **Class** | **CREDENTIALLED TEST** — runnable on the free sample |
| **Evidence needed** | Whether a security whose sector changed carries one row or a dated series. |
| **Dataset / endpoint** | TICKERS |
| **Smallest sample** | A handful of securities with known reclassifications. |
| **Pass condition** | Dated classification history present. |
| **Blocking failure** | Not blocking. `CLASSIFICATION_STATIC` is explicitly acceptable for paper research provided it is declared, never silently used. |
| **Credentials** | Yes. Sample tier sufficient. |
| **Paid access** | No |
| **`.runtime/` artifact** | Observed row shape per security |
| **Committable** | The limitation token, as configuration |
| **Public-doc status now** | The retrieved TICKERS schema shows one current row per ticker with no dated classification series (`PSR-SHD-096`), so `CLASSIFICATION_STATIC` is the **expected** outcome. Not conclusive: the fetch enumerated identity and date fields, and did not exhaustively enumerate classification fields. |

| | P5 |
|---|---|
| **Test (verbatim)** | **Adjusted/raw reconciliation.** Recomputing adjusted from raw + actions reproduces the vendor's adjusted series. |
| **Objective** | Prove the adjustment pipeline is correct before anything is built on adjusted prices. |
| **Class** | **CREDENTIALLED TEST** — runnable on the free sample |
| **Evidence needed** | For securities with splits and dividends in range: raw OHLC, the vendor's adjusted close, and the actions, reconciling within tolerance. |
| **Dataset / endpoint** | SEP (unadjusted, split-adjusted, and split+dividend+spinoff adjusted — `PSR-SHD-097`) + ACTIONS |
| **Smallest sample** | 5–10 securities with at least one split and several dividends. |
| **Pass condition** | Recomputed series matches the vendor's within tolerance, **and** differs from a today-adjusted series at dates before the split (acceptance criterion 3). |
| **Blocking failure** | Data-quality check 5.6 blocks the dataset. |
| **Credentials** | Yes. Sample tier sufficient — DJIA names have splits and dividends in a 5-year window. |
| **Paid access** | No |
| **`.runtime/` artifact** | Reconciliation output, tolerance, mismatches |
| **Committable** | The adjustment implementation and its **synthetic-fixture** tests. Not the reconciliation results (§3.E). |
| **Public-doc status now** | **Favourable and self-contained.** Three adjustment methods are published, raw and adjusted both supplied (`PSR-SHD-097`), so no second vendor is needed. |

| | P6 |
|---|---|
| **Test (verbatim)** | **Known-restatement qualification.** Take a company with a documented multi-step restatement. Confirm each intermediate revision is present with its own distinct availability time, and that a query at a date between two restatements returns the one then current. |
| **Objective** | Decide whether `AS_KNOWN_AT_AS_OF` is a guarantee or a declared two-point approximation. |
| **Class** | **PURCHASE-DEPENDENT TEST** |
| **Evidence needed** | A company with a documented multi-step restatement; each intermediate revision present with a distinct availability time. |
| **Dataset / endpoint** | SF1 (ARQ and MRQ) + EDGAR amended filings |
| **Smallest sample** | One well-documented multi-step restatement — but it must be *found*, and finding it needs depth. |
| **Pass condition** | Every intermediate revision present and separately timed. |
| **Blocking failure** | `revision_chronology_completeness = FIRST_AND_LATEST_ONLY`; every dependent run carries `REVISION_CHRONOLOGY_INCOMPLETE`; `AS_KNOWN_AT_AS_OF` becomes a declared two-point approximation. |
| **Credentials** | Yes |
| **Paid access** | **Yes**, and depth matters — restatement chains rarely sit inside five years. |
| **`.runtime/` artifact** | The restatement chain, revisions observed, availability times |
| **Committable** | The completeness enum and limitation token, as configuration |
| **Public-doc status now** | **Documentation already gives the answer, and it is adverse.** AR excludes restatements; MR is updated **in place** and indexed to the report period, so a restated value carries no time at which it became knowable (`PSR-SHD-101`, `PSR-SHD-079`). P6 stays **blocking** anyway, per ADR-0003 §4: verify against real data rather than trusting a doc page. **`AS_KNOWN_AT_AS_OF` must come from EDGAR**, and EDGAR is therefore not a cross-check but the only source. |

| | P7 |
|---|---|
| **Test (verbatim)** | **Filing-linkage.** Every fundamental row resolves to a filing with an acceptance timestamp. |
| **Objective** | Establish whether public availability is exact or lagged. |
| **Class** | **CREDENTIALLED TEST**, plus working EDGAR access |
| **Evidence needed** | A sample of SF1 rows each resolving to a specific EDGAR filing with an acceptance timestamp. |
| **Dataset / endpoint** | SF1 + EDGAR submissions |
| **Smallest sample** | ~50 rows across filer sizes and eras. |
| **Pass condition** | Every row resolves. |
| **Blocking failure** | Not blocking. The §9 vendor lag applies and is declared. |
| **Credentials** | Yes, plus EDGAR access — **currently unverified from this environment** (`PSR-SEC-045`). |
| **Paid access** | No |
| **`.runtime/` artifact** | Linkage rate, unresolved rows, lag distribution |
| **Committable** | The linkage rule and declared lag |
| **Public-doc status now** | The retrieved SF1 schema lists `date` ("Date Key"), `reportperiod` and `calendardate`, **and no `filingdate` column** (`PSR-SHD-101`), while AR is documented as indexed to the filing date. Whether the Date Key **is** the filing date is the crux and is unconfirmed (`PSR-SHD-078` remains open). |

| | P8 |
|---|---|
| **Test (verbatim)** | **Earnings-timing fidelity.** Compare vendor announcement timing against 8-K acceptance times on a sample. |
| **Objective** | Decide whether `EARNINGS_TIME_APPROXIMATED` is declared. |
| **Class** | **PUBLIC-DOC PRECHECK — effectively answered** |
| **Evidence needed** | Whether the vendor supplies a time at all. |
| **Dataset / endpoint** | EVENTS + EDGAR 8-K acceptance times |
| **Smallest sample** | None for the schema question; a sample only for lag characterisation. |
| **Pass condition** | Vendor timing matches 8-K acceptance times within tolerance. |
| **Blocking failure** | Not blocking. `EARNINGS_TIME_APPROXIMATED` is declared. |
| **Credentials** | Yes for lag characterisation |
| **Paid access** | No |
| **`.runtime/` artifact** | Timing comparison, lag distribution |
| **Committable** | The limitation token and event-window policy |
| **Public-doc status now** | **Answered on the schema question.** EVENTS is 8-K-derived and carries a **filing date only, no time component and no before/after-market indicator**, from January 2004 (`PSR-SHD-100`). The token applies. **EDGAR acceptance timestamps are the only route to intraday timing** — conservative in the safe direction, since 8-K acceptance can only delay information, never advance it. Note the January 2004 start is six years later than prices and fundamentals. |

| | P9 |
|---|---|
| **Test (verbatim)** | **Bar construction and origin.** Are the daily bars officially disseminated (consolidated tape), aggregated by the provider from its own trade collection, or resampled by us? |
| **Objective** | Fix `price_bar.information_origin`, which decides `PUBLIC_PIT` eligibility for prices **and everything derived from them**. |
| **Class** | **VENDOR-CLARIFICATION — none of the three given classes fits. Flagged at §6.0.** |
| **Evidence needed** | A vendor statement of provenance. **No data sample can supply this.** |
| **Dataset / endpoint** | SEP — but the answer is not in the data |
| **Smallest sample** | Not applicable |
| **Pass condition** | Origin established and recorded per dataset. |
| **Blocking failure** | If `PROVIDER_AGGREGATED`: **price data and everything derived from it — including the universe — are ineligible under `PUBLIC_PIT`.** The implementation plan calls this larger in consequence than the estimates gap. |
| **Credentials** | **No — credentials do not help.** |
| **Paid access** | **No — purchase does not answer it.** |
| **`.runtime/` artifact** | The vendor's written statement |
| **Committable** | The recorded origin per dataset, as configuration |
| **Public-doc status now** | **Not stated.** The prices documentation covers delivery frequency and reporting lag but not construction or source (`PSR-SHD-098`). Carried as **Q7** in §4. **Answer this before purchase, not after** — it is the cheapest question in the set and the most expensive to get wrong. |

### 6.2 What the free sample would and would not reach

| | P1 | P2 | P3 | P4 | P5 | P6 | P7 | P8 | P9 |
|---|---|---|---|---|---|---|---|---|---|
| Answerable from public docs today | indicative | no | **yes** | indicative | favourable | indicative | partial | **yes** | **no** |
| Runnable on the free sample | partial | **no** | n/a | **yes** | **yes** | **no** | partial | partial | **no** |
| Requires a paid subscription | confirm | **yes** | no | no | no | **yes** | no | no | **no** |
| Requires Full History depth | no | **yes** | no | no | no | **likely** | no | no | no |

**Reading of the row that matters:** P2 and P6 — the two tests whose failure would be
structural — are the two that **cannot** be de-risked before purchase, and both need the Full
History tier. Everything else is either already answered or reachable at zero subscription cost.
That shapes the purchase decision more than any price does.

---

## 7. Cost comparison

### 7.1 A correction to the recorded cost of the recommended stack

**Sharadar Direct is tiered by history depth, and the $29/mo Bundle recorded in round 1 buys
five years** (`PSR-SHD-090`).

Phase 3 acceptance criterion 2 requires a universe snapshot for a date **at least eight years
past** containing securities delisted since, and states that zero delisted members **fails**.
P2 samples delistings at 5, 10 and 15 years. **A five-year product cannot satisfy either.**

| Plan | 5 years | 10 years | **Full History** |
|---|---|---|---|
| Fundamentals | $19/mo · $199/yr | $29/mo · $299/yr | $39/mo · $399/yr |
| Prices | $9/mo · $99/yr | $19/mo · $199/yr | $39/mo · $299/yr |
| Investors | $19/mo · $99/yr | $29/mo · $199/yr | $39/mo · $299/yr |
| **Bundle** | $29/mo · $299/yr | $49/mo · $399/yr | **$69/mo · $499/yr** |

All figures `PSR-SHD-090`, retrieved 2026-08-27. **Re-verify on the day of purchase** — the
register's maintenance rule, and the reason this correction exists at all.

> **"Full History" is not defined on the pricing page** (`PSR-SHD-091`). The documentation
> states January 1998 for prices and fundamentals and January 2004 for events
> (`PSR-SHD-099`, `PSR-SHD-101`, `PSR-SHD-100`), and the vendor's own launch post says
> *"since 1999"* (`PSR-SHD-104`) — **two vendor statements that disagree by a year.** For a
> plan whose central control is survivorship, purchasing a depth that is stated nowhere and
> described inconsistently is a defect in the purchase, not a rounding error. It belongs in the
> clarification questions.

### 7.2 Restated scenario A

| Item | Round 1 | **Corrected** |
|---|---|---|
| Sharadar Bundle | $29/mo → **$348/yr** | **$499/yr** (Bundle Full History, annual) |
| SEC EDGAR | $0 | $0 |
| LEAN calendars · `exchange_calendars` | $0 | $0 |
| **Total recurring** | **~$348/yr** | **~$499/yr** |

The monthly route to the same product is $69/mo = **$828/yr**, so annual billing saves ~$329/yr
at the cost of committing for a year — against §9's no-refund-on-cancellation policy
(`PSR-SHD-045`) and §10's immediate-termination right (`PSR-SHD-085`). **A monthly first term
is the more conservative purchase** while G3 is unresolved, and is the recommendation if a
purchase is ever authorized.

Scenarios B and C are **not** re-costed here. Both rest on QuantConnect figures whose
organization-tier price remains `[U]` (`PSR-QC-035`), and re-verifying them is work for the day
a purchase is actually contemplated.

### 7.3 Against the V3 budget

| | |
|---|---|
| Base annual data budget | **$1,500** |
| Conditional ceiling | **$5,000/yr** |
| **Corrected scenario A** | **$499/yr — 33% of base** |

**The ceiling is not a target and this packet proposes no spend.** The corrected figure is still
comfortably inside base budget, so the price change does not alter the recommendation — it
alters what the money buys, which is the point of recording it.

### 7.4 Priority order applied

The task's stated priorities, applied to what was found:

| Priority | How the candidate stack scores |
|---|---|
| 1. **Point-in-time correctness** | Mixed, and known. AR fundamentals are genuinely filing-date-indexed. Revision chronology is absent (P6). Provider availability is bounded, not exact (P1). Bar origin is **unknown** (P9). |
| 2. **Licensing fitness** | **The blocker.** §10 retention, §8 disclosure, and an FAQ-only core permission. §3. |
| 3. **Retained research reproducibility** | **Materially constrained by §10** — reproducibility does not survive cancellation. §3.C. |
| 4. **Required Phase-3 coverage** | Good, with two documented gaps: no corporate-action announcement date (P3), and ticker history as a derived artifact (§5.3). |
| 5. **Cost** | $499/yr, one third of base budget. **The least binding constraint, and it should not drive the decision.** |

---

## 8. Alternative-provider comparison

Deliberately lightweight: only alternatives that could **change the decision**. Round 1's
survey stands and is not repeated.

| | **Sharadar Direct** | EODHD | Norgate | Massive | QuantConnect / AlgoSeek | Institutional PIT |
|---|---|---|---|---|---|---|
| PIT semantics | AR filing-date-indexed; **no revision chronology** | **no PIT claim** | not a PIT fundamentals product | not a PIT fundamentals product | security master + prices; not fundamentals PIT | **genuine**, two availability axes |
| Delisted / security master | active + delisted, 1998– | delisted coverage claimed | 1990–, but **no historical ticker mapping** | since 2003-09-10 | ~27,500 equities from 1998 | full |
| Ticker history | **derived** from ACTIONS (§5.3) | unverified | **absent** — disqualifying | ticker events | map files | full |
| Corporate actions | yes; **no announcement date** | yes | documented; history not static | yes | ex-date keyed factor files | full |
| Fundamentals / events | AR + MR; 8-K events date-only | fundamentals, no PIT | — | — | — | full |
| Revisions / restatements | **two-view only** | — | — | — | — | **full chronology** |
| Personal-use licensing | Personal Use License; **§3 issues** | personal plans; commercial separate | — | individual/non-professional | CLI display/distribution barred | n/a — institutional |
| Local retention | **§10 delete on termination** | not established | — | — | LEAN-engine-bound | contractual |
| API suitability | REST + bulk; **key in query string** | REST | — | REST | LEAN | enterprise |
| **Annual cost** | **$499** (Full History Bundle) | $999.90 ALL-IN-ONE | $630 (Platinum) | $348–$2,388 | $600/yr master + $2,136 bulk | **`[Q]`** |
| Likely P1–P9 fitness | **best available at this price** | fails the PIT premise | fails on identity | not fundamentals-capable | complements, does not replace | would pass — unaffordable |

Sources: `PSR-SHD-090`, `PSR-EOD-050`, `PSR-NRG-018`, `PSR-MSV-030`, `PSR-QC-017`,
`PSR-QC-018`, `PSR-MISC-021`, `PSR-MISC-024`.

### Why Sharadar remains preferred

1. **It is the only candidate at a published personal-use price that makes an as-reported,
   filing-date-indexed point-in-time claim at all** (`PSR-SHD-101`). EODHD is cheaper per
   feature and makes no such claim (`PSR-EOD-039`) — that is not a cheaper version of the right
   product, it is a different product.
2. **Norgate is disqualified on identity, not price**, and this round makes the contrast
   precise: both lack a supplied ticker mapping, but only Sharadar supplies the dated change
   log that makes one reconstructable (§5.3).
3. **One licence covers security master, prices, actions, events and fundamentals.** Splitting
   domains across vendors multiplies both licensing surface and identity-join risk — the risk
   class that corrupts everything downstream silently.
4. **The alternatives that would fix the real gaps are institutional.** S&P Capital IQ Premium
   Financials describes exactly the two-axis model the KalpaMani contract needs
   (`PSR-MISC-024`) and is quote-only. So is every genuine PIT estimates source
   (`PSR-MISC-021`). **There is no mid-market rung on this ladder.**
5. **Cost is not why.** At $499/yr against a $1,500 base budget, price is the least binding
   constraint in the comparison, and the recommendation would be the same at twice the price.

### What would displace it

Recorded so the conclusion is falsifiable rather than merely stated:

- **Q7 / P9 answered "provider-aggregated"** — prices and the universe become ineligible under
  `PUBLIC_PIT`, and a second price source becomes mandatory rather than a cross-check.
- **Q1 answered adversely** — if own-capital automated trading needs a professional licence,
  the whole comparison reruns at commercial prices, which are unpublished on **both** the
  vendor and the Nasdaq channel (`PSR-SHD-071`, `PSR-MISC-023`).
- **P2 failing on real data** — delisted coverage is the one claim no documentation can
  discharge and the one whose absence is fatal.

---

## 9. G4 and G5 observations

**Neither gate is decided here. Both remain OPEN.**

### G4 — analyst estimates and revisions

**Observation, not a decision.** No evidence found this round changes round 1's conclusion, and
one new source corroborates it from a different direction: the vendors that supply genuine
point-in-time fundamentals with per-revision availability — S&P Capital IQ Premium Financials,
Bloomberg via Data License — are institutional and quote-only (`PSR-MISC-024`), matching what
round 1 found for estimates specifically (`PSR-MISC-021`).

**Does the preferred provider clearly supply genuine historical point-in-time analyst revision
history? No.** Sharadar has no estimates product; that is not a defect, it is scope.

The evidence is not *unusually definitive* in the direction that would justify closing G4 — it
is definitive about what is **absent**, which is a different thing. Round 1's recorded position
stands: build the Blueprint §6 composite from its PIT-available sub-components, mark the
revision sub-factor `ANALYST_REVISIONS_UNAVAILABLE`, attribute no performance to it, and propose
no change to the Blueprint weights. **The one open lead — whether Zacks Data direct supplies
genuine as-of consensus snapshots, and at what price (`PSR-EST-068`) — is a sales conversation,
which is authorization A5 and was not performed.**

### G5 — borrow history

**No claim is made that this stack solves historical borrow, and none could be.** Sharadar is a
price and fundamentals provider; borrow is not in its catalogue. Nothing in this round's
evidence touches it.

The Phase 3C ordering recorded in [provider-evaluation.md](provider-evaluation.md) §2.9 is
unchanged and remains correct, cheapest-first:

1. IBKR `FEE_RATE` historical depth via the TWS API — **requires A6; no broker interaction was
   performed or is authorized**
2. Verify the S3 Partners AWS Data Exchange listing — genuinely free and broad, or a sample?
3. Orbisa premium via the IBKR dashboard — 12 months, day resolution, UI only
4. ORTEX — credit economics **and** depth, before any commitment
5. Institutional — `[Q]`

**No new public borrow candidate was discovered this round.** No borrow source was contacted,
priced or accessed. The standing rules are untouched: current IBKR availability must not be
represented as historical borrow availability, and **short backtesting remains forbidden until a
source qualifies** (ADR-0005 §15).

---

## 10. Proposed next decision

**For the owner. This packet decides nothing and authorizes nothing.**

### The decision requested

> **Should the six licensing-clarification questions in §4 be sent to Sharadar at the published
> contact route (`PSR-SHD-106`), together with question Q7 on bar construction?**

A yes is authorization to send correspondence. It is **not** authorization to purchase, to
trial, to create an account, to enter billing details, to generate an API key, or to fetch
anything.

### Why this is the next decision and not something else

- **G3 gates G1's purchase** by ADR-0005's own ordering (authorization A2 precedes A3). Any
  qualification work done before the licensing answers risks being work done under terms that
  turn out not to permit it.
- **Two of the answers change the architecture, not just the paperwork.** Q4 decides whether
  reproducibility survives cancellation. Q5 decides how P1–P9 evidence can be reviewed at all
  in a repository that reviews in public. Neither is a detail to settle after a purchase.
- **Q7 is nearly free and potentially decisive.** A `PROVIDER_AGGREGATED` answer would make
  prices and the universe ineligible under `PUBLIC_PIT`. Asking costs one sentence.

### Options the owner may take instead

| Option | Consequence |
|---|---|
| **Send §4 + Q7** *(recommended)* | Answers arrive; G3 becomes decidable; the packet is revised; **only then** does a purchase decision arise |
| **Authorize a free-sample precheck first** | $0, no subscription. Would exercise P4 and P5 and partially P1, and would confirm undocumented per-action semantics (§5.3). **Still requires its own authorization** — the sample is Services Data under the same Terms, and reading it is vendor-data retrieval |
| **Accept the §10 and §8 constraints as-is and proceed to purchase** | Legitimate if the owner accepts that reproducibility ends 30 days after cancellation and that provider-test evidence stays undisclosed. **Requires an explicit recorded acceptance**, not silence |
| **Defer Phase 3A A2 entirely** | Also legitimate. Nothing here is time-critical, and no provider commitment exists |

### What is needed to close G3 and G1 later

**Neither is closed by this document.**

| Gate | Remaining |
|---|---|
| **G3** | Written answers to Q1–Q6; owner acceptance or rejection of the §10 retention consequence; an ADR or recorded decision; then authorization A2 |
| **G1** | G3 closed first; Q7/P9 answered; P1–P9 executed against real data under A3; scenario A/B/C selected; then ADR-0005 moves from Proposed |

---

## 11. Explicit non-authorizations

This document is research and documentation. **It grants no authority whatsoever.**

Nothing here authorizes, and nothing here has performed:

> purchasing anything · starting any free or paid trial · creating a vendor account · entering
> billing information · generating, requesting, entering or storing an API key · downloading
> subscribed or sample vendor data · calling any vendor API, authenticated or otherwise ·
> contacting any provider, by email, ticket or form · SEC bulk ingestion implementation ·
> provider client implementation · Bronze/Silver/Gold real-data ingestion · A2 or A3
> implementation · Phase 3B, 3C or 3D implementation · closing G1 or G3 · accepting ADR-0005 ·
> strategy, Brain, scanner or factor work · broker or LEAN activity of any kind

**Gate status, unchanged by this document: G1 OPEN · G2 OPEN · G3 OPEN · G4 OPEN · G5 OPEN ·
G6 OPEN · G7 OPEN.**
**ADR-0005 remains PROPOSED. Live trading remains HARD-DISABLED.**

**Activity record for this round:**

| | |
|---|---|
| Provider purchase / trial / credential activity | **NONE** |
| Vendor accounts created | **NONE** |
| API keys requested, generated, entered or stored | **NONE** |
| Vendor data fetched — including the free sample and the published test key | **NONE** |
| Providers contacted | **NONE** |
| Broker or LEAN activity | **NONE** |
| Network activity | Public web pages only: vendor documentation, published terms, published pricing, one vendor blog post, one government site (which blocked every request), and search |

---

## 12. Sources and retrieval dates

All retrieved **2026-08-27** unless noted. Every claim resolves to
[provider-source-register.md](provider-source-register.md) section `R2`.

### Official primary sources — Sharadar

| Source | URL | Claims |
|---|---|---|
| Personal Use License Terms — all 18 sections | `https://sharadar.com/terms` | `PSR-SHD-081`…`089` |
| Subscribe / pricing | `https://sharadar.com/subscribe` | `PSR-SHD-090`, `091`, `092` |
| Documentation — Fundamentals | `https://sharadar.com/docs/fundamentals` | `PSR-SHD-093`, `101` |
| Documentation — Corporate Actions | `https://sharadar.com/docs/actions` | `PSR-SHD-094`, `095` |
| Documentation — Tickers and Metadata | `https://sharadar.com/docs/tickers` | `PSR-SHD-096` |
| Documentation — Stock Prices | `https://sharadar.com/docs/stocks` | `PSR-SHD-097`, `098`, `099` |
| Documentation — Material Corporate Events | `https://sharadar.com/docs/events` | `PSR-SHD-100` |
| Documentation — Authentication | `https://sharadar.com/docs/auth` | `PSR-SHD-102` |
| Documentation — FAQs | `https://sharadar.com/docs/faqs` | `PSR-SHD-107` |
| Documentation — Bulk Downloads | `https://sharadar.com/docs/bulk` | `PSR-SHD-105` *(unreadable)* |
| Sample dataset | `https://sharadar.com/sample` | `PSR-SHD-103` |
| Privacy Policy | `https://sharadar.com/privacy` | `PSR-SHD-106` |
| Blog — Sharadar Launches Direct, **dated 2026-07-27** | `https://blog.sharadar.com/2026/07/sharadar-launches-direct.html` | `PSR-SHD-104` |

### Government and other

| Source | URL | Claims |
|---|---|---|
| SEC.gov — block response served on every path attempted | `https://www.sec.gov/...` | `PSR-SEC-045` |
| SEC EDGAR fair access — secondary corroboration | search-index summaries | `PSR-SEC-046` |
| SEC website policies — trademark and seal | search-index summaries | `PSR-SEC-047` |
| Internet Archive — unreachable | `https://web.archive.org/...` | `PSR-SEC-048` |
| EODHD pricing | `https://eodhd.com/pricing` | `PSR-EOD-050` |
| Nasdaq Data Link terms — **not retrievable** | `https://data.nasdaq.com/terms` | `PSR-MISC-023` |
| S&P Global / Bloomberg PIT fundamentals | search-index summaries | `PSR-MISC-024` |

### Repository sources

[CLAUDE.md](../../CLAUDE.md) · [ADR-0005](../decisions/ADR-0005-point-in-time-data-architecture.md) ·
[ADR-0006](../decisions/ADR-0006-adopt-blueprint-v3-and-strategy-brain-governance.md) ·
[implementation-plan.md](implementation-plan.md) (P1–P9, verbatim) ·
[pit-data-contract.md](pit-data-contract.md) · [conceptual-schema.md](conceptual-schema.md) ·
[data-quality-plan.md](data-quality-plan.md) ·
[reproducibility-and-provenance.md](reproducibility-and-provenance.md) ·
[provider-evaluation.md](provider-evaluation.md) ·
[provider-source-register.md](provider-source-register.md) ·
[phase3a-a1-foundation-kernel.md](phase3a-a1-foundation-kernel.md)

### Retrieval limitations, recorded rather than papered over

| Limitation | Effect |
|---|---|
| **sec.gov blocked, second consecutive round** — six paths, two client types, all returning the SEC's *"Request Rate Threshold Exceeded"* page | Every EDGAR field claim stays `V2`; the exact User-Agent format stays unestablished |
| **Internet Archive unreachable** | No fallback route to verbatim SEC policy text exists from this environment |
| **Nasdaq Data Link terms not retrievable**; searches surface Nasdaq *exchange* market-data agreements, a different product family | The commercial channel's terms **cannot be assessed from public sources at all** — material for any future entity or micro-live use |
| **Sharadar bulk-downloads documentation client-side rendered behind a session check** | File formats, size limits and download quotas remain unestablished |
| **Licence quotations are model-mediated** — the fetch tool summarised rather than reproducing verbatim | **A reviewer should open the URLs and confirm any string before relying on it in a compliance decision** |
| **Prices and terms change**, and the Terms page carries no version or effective date | Every figure and clause here must be re-verified on the day of purchase, per the register's maintenance rule |
