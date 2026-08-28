# ADR-0008 — Sharadar Personal Use Licence Accepted; Private Sample Qualification

**Status:** **Accepted — effective on the merge of the pull request that introduces this ADR.**
Until that merge it is proposed and carries no authority.
**Date:** 2026-08-27
**Deciders:** Project owner (human governance)
**Supersedes:** the recommendation **B — NEED WRITTEN LICENSING CLARIFICATION FIRST** in
[provider-licensing-decision-packet.md](../phase3/provider-licensing-decision-packet.md) §1, and
the **OPEN** status of decision gate **G3** *for Sharadar personal use only*. Nothing else in that
packet, and no other gate.
**Superseded by:** —
**Relates to:** [ADR-0005](ADR-0005-point-in-time-data-architecture.md) (the gate model and the
point-in-time contract), [ADR-0006](ADR-0006-adopt-blueprint-v3-and-strategy-brain-governance.md)
(Blueprint V3.0 authority), [ADR-0007](ADR-0007-cloud-first-research-data-plane.md) (the private
AWS location for licensed data, and the deletion-first posture this decision depends on)
**Authority:** Blueprint V3.0 §17, §19 · CLAUDE.md §4.22, §4.23

---

## 1. Context

[ADR-0005](ADR-0005-point-in-time-data-architecture.md) opened five decision gates; Blueprint V3.0
added two. **G3 — vendor licensing** asked whether the governing licence permits what KalpaMani
intends to do with the data.

The [G1/G3 decision packet](../phase3/provider-licensing-decision-packet.md) answered that from
public sources on 2026-08-27 and returned recommendation **B — need written licensing
clarification first**, on three findings:

1. **§10 post-termination deletion is wider than ADR-0005 assumed.** It reaches every dataset that
   *could reproduce* the vendor's tables, so bronze, silver and reconstructable gold artifacts are
   all inside it, and **durable re-execution from source does not survive cancellation**.
2. **§8 bars private disclosure, not only publication.** Empirical conclusions about the value,
   usability or fitness of the Services or the Services Data may not be published *or otherwise
   disclosed to any outside individual or entity* without prior written approval.
3. **The permission KalpaMani most needs sits in an undated FAQ**, not in the licence, under §18
   terms the vendor may amend unilaterally.

The packet drafted eight questions — Q1–Q8 — at
[provider-licensing-clarification-draft.md](../phase3/provider-licensing-clarification-draft.md),
and asked the owner to decide whether to send them.

**The owner has decided not to send them, and to accept the published terms as they stand.** This
ADR records that decision, the constraints it carries, and exactly how far it reaches.

### Public sources re-verified for this decision

Re-read on **2026-08-27** and recorded in
[provider-source-register.md](../phase3/provider-source-register.md) §R3. Nothing material had
changed since the packet's round:

| Source | Bearing on this decision |
|---|---|
| `https://sharadar.com/terms` | Eighteen sections; **still no version number and no effective date** |
| `https://sharadar.com/docs/faqs` | Personal Use covers *research, backtesting, and automated trading of their own account with no external clients or money managed for others* |
| `https://sharadar.com/docs/auth` | A key is passed **in the query string**; a vendor-published test key exists and is documented for AAPL queries |
| `https://sharadar.com/sample` | Free sample: 30 DJIA names, 5 years, sign-in required |

**No Sharadar API was called. No Services Data was retrieved, inspected or evaluated to reach this
decision.** Everything above is the vendor's own public website.

---

## 2. Decision

**The owner accepts the Sharadar Personal Use License as currently published**, for:

- individual personal research;
- personal backtesting;
- programmatic API use;
- automated trading of **the owner's own account**, where permitted by the published Sharadar
  documentation.

**No separate licensing email is required before continuing.** The eight-question clarification
draft is:

> **CANCELLED · NOT SENT · HISTORICAL EVIDENCE ONLY**

It is **not deleted**. It stays at
[provider-licensing-clarification-draft.md](../phase3/provider-licensing-clarification-draft.md)
as the record of what public research could not settle, and of the decision taken instead.

**Gate G3 becomes RESOLVED / CLOSED for Sharadar personal use.**

### What this decision does NOT do

Stated as a list because each item is a separate authorization under CLAUDE.md §8, and none of
them is granted here:

```
Sharadar selected as the production provider     NO   -- G1 stays OPEN
G1 closed                                        NO
G2 closed                                        NO
G4 / G5 / G6 / G7 closed                         NO
a subscription purchased                         NO
a vendor account created                         NO
a private API key requested or held              NO
production ingestion authorized                  NO
A2 / A3 production implementation authorized     NO
ADR-0005 accepted                                NO   -- it remains PROPOSED
Phase 3 complete                                 NO
```

**If the provider changes away from Sharadar, G3 reopens for the replacement provider.** This
decision is about one licence, not about licensing in general.

### Why the owner may decide this against recommendation B

Recorded so the decision is reviewable rather than merely asserted. Recommendation B was a
recommendation, not a finding of prohibition — the packet's own §1 says it is *not* a finding that
Sharadar is unsuitable. The three findings survive this decision and are carried forward as
**accepted constraints** in §3 below rather than as unanswered questions.

Two of them the architecture already accommodates: ADR-0007 built the licensed store
deletion-first, which is what §10 requires, and the private-report boundary in §3.C is exactly the
design the §8 disclosure limb forces. The third — an FAQ-sourced permission under amendable terms
— is a residual risk the owner accepts for a **$0, unsubscribed, public-test-key** qualification
probe, a materially smaller exposure than the purchase the packet was sequencing toward.

---

## 3. The licence constraints this decision retains

Accepting the licence is accepting these. They are binding on every future session.

### A. Personal use only

Use is by the owner **as a natural person**. Prohibited, and each of these voids the licence rather
than merely straining it:

```
employer use          client use            external money management
entity use            fund use              institutional use
redistribution
```

**Consequence carried forward:** §3 of the licence is not available to legal entities. If
KalpaMani is ever operated through an LLC, trust or partnership, **the licence must change at the
same moment** — and CLAUDE.md §3 separately requires the repository to be private before micro-live
or real money.

### B. Services Data stays private

Sharadar raw rows, and anything provider-derived from them, may be processed by **deterministic
KalpaMani code inside the private deployment boundary**. They may **not** be:

```
committed to GitHub          pasted into an AI chat        read into a Claude context
sent to an external LLM API  placed into shared SaaS       redistributed in any form
```

This is CLAUDE.md §4.22 applied to a named vendor. It is not new policy; it is the same rule with
the vendor now identified.

### C. Empirical provider evaluation is private

Sharadar Terms **§8** restricts disclosure and publication of conclusions drawn from testing or
evaluating the Services or the Services Data. It bars publication **and** disclosure to any outside
individual or entity.

Therefore the following are **private artifacts**:

| |
|---|
| empirical P1–P9 observations |
| pass/fail detail from a live run |
| sampled vendor rows |
| provider-quality conclusions |
| the private qualification recommendation |

They belong **only** in:

- the **licensed** S3 bucket, under the `qualification/` prefix — inside the deletion surface;
  and/or
- git-ignored `.runtime/` storage, for owner review.

They do **not** belong in Git, in a pull request, in a GitHub issue, in a commit message, or in any
AI session — Claude, ChatGPT or otherwise.

> **Why the owner reading their own report is not a §8 disclosure.** The owner is the licensee.
> §8's disclosure limb reaches an **outside** individual or entity; material that never leaves the
> licensee's own private storage has not been disclosed to anyone. What the limb does reach is a
> pull-request reviewer, a public repository, and an external model provider — which is precisely
> why the boundary is drawn where it is, and why the harness cannot print its conclusion.

**Public documentation may still describe:** methodology, public vendor documentation,
architecture, and limitations already apparent from public documentation. That is what this ADR and
the harness's own source code do, and it is why both are safe to commit.

### D. Termination

[vendor-data-cloud-deletion.md](../runbooks/vendor-data-cloud-deletion.md) remains the authoritative
procedure for the **30-day** deletion obligation, which §10 permits to start **without prior
notice**.

**Qualification material is LICENSED and sits inside the deletion surface.** The runbook already
enumerates `qualification/` among the prefixes it destroys; that placement is now load-bearing
rather than anticipatory.

### E. Third-party AI

Sharadar's **public documentation** may be used by an AI assistant — this ADR was written that way.
That grants **no** permission to send **Services Data**, or private empirical evaluation results, to
an external AI provider. The two are different things, and the distinction is the whole boundary.

---

## 4. Gate status after this ADR

**The exact map. No blanket "G1–G7 are all OPEN" statement is correct any longer.**

| Gate | Subject | Status |
|---|---|---|
| **G1** | provider selection / qualification | **OPEN** |
| **G2** | production information-set profile | **OPEN** |
| **G3** | vendor licensing — Sharadar personal use | **CLOSED** |
| **G4** | analyst estimates and revisions | **OPEN** |
| **G5** | historical borrow | **OPEN** |
| **G6** | options overlay | **OPEN** |
| **G7** | strategy-taxonomy evidence | **OPEN** |

**ADR-0005 remains PROPOSED. Phase 3 remains NOT COMPLETE. Live trading remains HARD-DISABLED.**

### Supersession of the historical all-gates-open statements

[ADR-0006](ADR-0006-adopt-blueprint-v3-and-strategy-brain-governance.md) and
[ADR-0007](ADR-0007-cloud-first-research-data-plane.md) each state that G1 through G7 are all open.
That was true on the day each was accepted, and **neither ADR is edited** — the repository does not
rewrite accepted decisions, exactly as it does not edit a Blueprint PDF
([ADR-0003](ADR-0003-broker-side-order-controls-are-not-safety-invariants.md) set that precedent).

Those two statements are **historical as of this ADR, and superseded for G3 alone.** Every other
gate they name is still open, and the table above is the current map.

---

## 5. Consequence — the private free-sample qualification harness

Closing G3 makes a **$0, unsubscribed** qualification probe permissible for the first time. It does
not make it automatic, and this ADR authorizes the *harness*, not a purchase.

| | |
|---|---|
| Credential | the **vendor-published public test key** documented at `https://sharadar.com/docs/auth` |
| Subscription | **NONE** — no paid plan, no trial |
| Vendor account | **NONE** — not required for the published test key |
| Secrets Manager entry | **NONE** |
| Coverage the key reaches | per the vendor's documentation, AAPL across the tables |
| Who runs it | **the owner, manually, after this pull request is merged** |
| Who never runs it | any AI session, `pytest`, CI, a preflight, or the docs audit |

The harness is
[`scripts/sharadar_private_qualification.py`](../../scripts/sharadar_private_qualification.py). Its
methodology is public; **its output is not**. Network access is off by default and requires an
explicit `--private-live-run` flag; the AWS identity gate must pass before any network call; and the
program's exit code reports **harness success or failure only** — never a provider verdict — so that
no automation log or AI transcript can become a disclosure channel.

> **A conservative treatment recorded deliberately.** The vendor does not separately state which
> licence governs data retrieved with the published test key; the sample page footer links the same
> Terms. This decision therefore treats **everything the harness retrieves as Services Data under
> the Personal Use License** — private storage, deletion surface, no external AI, no Git. Treating
> it as unlicensed because it is free would be the cheap reading, and the wrong one.

### What the harness does not do

```
no production provider adapter          no src/kalpamani/data/ingest/sharadar/
no S3ResearchObjectStore                no Parquet production writer
no DuckDB production catalog            no daily ingestion, no scheduler
no ECS research task, no ECR image      no provider secret, no paid retrieval
no new production dependency            no widening of the A1 package surface
```

Each of those is a separate written authorization under CLAUDE.md §8, and none is granted here.

---

## 6. Alternatives considered

| Alternative | Why not taken |
|---|---|
| **Send Q1–Q8 and wait** (packet recommendation B) | The owner's judgment is that a $0 unsubscribed probe against the vendor's own published test key does not warrant blocking on vendor correspondence. The questions remain valuable **before a purchase**, and the draft is retained for exactly that. |
| **Purchase now and qualify against the paid tiers** | Refused. G1 is open, P2 and P6 need the Full History tier, and buying before the free surface has been exercised inverts the cost ordering the packet established. |
| **Skip qualification and implement the adapter** | Refused. P1–P9 exist because a vendor datasheet is not evidence; ADR-0003's rule — verify against reality, never against a documentation page — applies directly. |
| **Change provider** | Refused. The packet's comparison found no alternative at a published personal-use price supplying as-reported filing-date-indexed fundamentals with delisted coverage, corporate actions and prices under one licence. |

---

## 7. Risks accepted

Recorded because a decision that hides its costs cannot be reviewed later.

| Risk | Owner's position |
|---|---|
| The own-capital permission rests on an **undated FAQ**, under §18 terms amendable at the vendor's sole discretion | Accepted. Exposure is bounded while nothing is purchased and nothing is subscribed. **Re-verify before any purchase.** |
| **No licence revision can be pinned** to a historical research run — the Terms page carries no version or effective date | Accepted, and recorded. Each qualification run stamps its own retrieval date, so the licence *as read that day* is at least identifiable. |
| **§10 deletion reaches bronze, silver and reconstructable gold**; durable re-execution from source does not survive termination | Accepted. ADR-0005 acceptance criterion 14 already fails loudly on a missing input, which is the contract behaving correctly. |
| §8 keeps empirical provider evidence **out of pull-request review** | Accepted, and it is why the private-report boundary in §3.C exists. The owner reviews that evidence alone. |
| The licence governing the **published test key** is not separately stated | Accepted, and treated conservatively: everything retrieved is handled as licensed Services Data. |

---

## 8. Explicit non-authorizations

Nothing in this ADR authorizes, and nothing here has performed:

> purchasing anything · starting any free or paid trial · creating a vendor account · entering
> billing information · requesting, generating, entering or storing a private API key ·
> subscribing · calling any vendor API from an AI session · contacting any provider ·
> production provider-client implementation · bronze/silver/gold real-data ingestion · A2 or A3
> implementation · Phase 3B, 3C or 3D implementation · closing G1, G2, G4, G5, G6 or G7 ·
> accepting ADR-0005 · strategy, Brain, scanner or factor work · broker or LEAN activity ·
> any AWS mutation · any further cloud spend

**Activity record for this decision:**

| | |
|---|---|
| Real Sharadar API calls | **NONE** |
| Sharadar Services Data retrieved, inspected, summarized or evaluated | **NONE** |
| Provider accounts created | **NONE** |
| Private API keys requested, generated, entered or stored | **NONE** |
| Paid subscriptions | **NONE** |
| Providers contacted | **NONE** |
| AWS mutations | **NONE** — the foundation was verified read-only |
| Broker or LEAN activity | **NONE** |
| Network activity | Public Sharadar website pages only |
