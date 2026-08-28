# ADR-0010 — Accept Bounded Sharadar Semantics and Authorize Qualification Subscription

**Status:** **Accepted — effective on the merge of the pull request that introduces this ADR.**
Until that merge it is proposed and carries no authority.
**Date:** 2026-08-28
**Deciders:** Project owner (human governance)
**Supersedes:** the standing description of **Q7 and Q8 as unresolved pre-purchase blockers** in
[ADR-0009](ADR-0009-sharadar-provider-realistic-implementation.md) §5 and in the
[cancelled clarification draft](../phase3/provider-licensing-clarification-draft.md). Nothing else.
It supersedes **no gate status**, no part of [ADR-0005](ADR-0005-point-in-time-data-architecture.md),
and no authorization boundary.
**Superseded by:** —
**Relates to:** [ADR-0005](ADR-0005-point-in-time-data-architecture.md) (the gate model and the
point-in-time contract), [ADR-0007](ADR-0007-cloud-first-research-data-plane.md) (the private AWS
location and the deletion-first posture), [ADR-0008](ADR-0008-sharadar-personal-use-license-and-private-qualification.md)
(the accepted personal-use licence, which G3 closes under), [ADR-0009](ADR-0009-sharadar-provider-realistic-implementation.md)
(the code-only provider integration this decision does **not** extend)
**Authority:** Blueprint V3.0 §11, §17, §19 · CLAUDE.md §4.21, §4.22, §4.23, §8

---

## 1. Context

[ADR-0009](ADR-0009-sharadar-provider-realistic-implementation.md) authorized a **code-only**
provider integration and left two questions standing as **pre-purchase blockers**:

- **Q7** — are the daily bars officially disseminated, or provider-aggregated?
- **Q8** — what depth does the Full History tier actually deliver, per table?

A public-source pass on 2026-08-28 left the two in **different** states, and the difference matters:
**Q7 remained publicly unresolved** — no first-party page answers the provenance question at all.
**Q8 was publicly bounded but not empirically verified** — the documentation does establish per-table
planning boundaries; what it cannot establish is the actual earliest records, completeness or
point-in-time behaviour of the delivered data. **The owner accepted both dispositions for
qualification.**

**This ADR records a governance decision and a completed purchase. It authorizes no access.**
Everything that would touch the vendor's systems — a credential, an API call, a download, ingestion
— remains separately unauthorized, and §8 states that exhaustively.

---

## 2. The decision

The owner decided:

> "I accept Q7 as publicly unresolved and require Sharadar price data to remain
> `PROVIDER_DERIVED` under `PROVIDER_REALISTIC_PIT`. I accept Q8 as sufficiently bounded for
> qualification, with actual earliest records and PIT behavior to be verified after purchase. I
> authorize purchase of one month of the Sharadar Personal Use Full History Bundle for up to
> USD 69 plus applicable tax. This does not close G1 or G2 and does not yet authorize credentials,
> API calls, Services Data ingestion, or production use."

**The owner confirmed that the qualification subscription was purchased and active**: a Sharadar
Bundle, Full History, monthly, Personal Use.

**No purchase screenshot, account identifier, account email, billing information, receipt, payment
information, credential, API key, or private licensing evidence is stored or committed in this
repository.** No private account page or API-key page was opened by the assistant preparing this
record, and no credential was retrieved or inspected. What this repository holds is the **owner-confirmed
commercial state** and nothing else — the authorization ceiling above is part of the decision; what
was actually charged is not this document's business.

---

## 3. Q7 — daily price-bar origin

| | |
|---|---|
| **Public resolution** | **`PUBLICLY_UNRESOLVED`** |
| **Governance disposition** | **OWNER-ACCEPTED FOR QUALIFICATION** |
| **Required classification** | **`PROVIDER_DERIVED`** |
| **Permitted historical profile** | **`PROVIDER_REALISTIC_PIT`** |

**No reviewed public first-party source establishes any of the following**, and the absence is the
finding:

- derivation from the CTA/UTP SIP;
- direct ingestion of an official consolidated tape;
- construction by Sharadar from raw exchange trades;
- a named upstream price-feed provider.

The pages read state *what* is delivered and *how it is adjusted*, and are silent on where it comes
from (`PSR-SHD-098`, `PSR-SHD-110`, `PSR-SHD-122`).

**Descriptive language is not provenance.** "Consolidated", "official exchange close" and
multi-exchange volume descriptions describe the *shape* of a number, not the *feed* it was built
from. Reading any of them as an origin claim is how an unverified assumption becomes a
classification, and a classification becomes a backtest that quietly assumes the market knew
something.

**Consequences, which are binding:**

- **All Sharadar price data remains `PROVIDER_DERIVED`.**
- The only permitted historical information-set profile for it is **`PROVIDER_REALISTIC_PIT`**.
- **Sharadar price data must never be represented as `PUBLIC_PIT`.** Under
  [`BAR_CONSTRUCTION_ORIGIN`](../../src/kalpamani/data/contracts/vocabulary.py), that is what
  `PROVIDER_AGGREGATED` implies, and this decision fixes the conservative side of it.
- **No artifact may be classified `PUBLIC_PIT` solely on the basis of Sharadar price data.** An
  artifact whose public classification is supported by an *independent* qualifying public source
  requires its own lineage and evidence, and **is not established by this ADR**. The rule is about
  what Sharadar data alone can support, not a permanent ceiling on every artifact that ever touches
  it — writing it the other way would block a future artifact whose public standing rests on evidence
  this decision never examined.

**This bounds the uncertainty; it does not resolve it.** The upstream origin is still unknown. What
has changed is that the unknown now has a documented, conservative disposition instead of an open
question blocking work.

---

## 4. Q8 — Full History depth

| | |
|---|---|
| **Public resolution** | **`PUBLICLY_BOUNDED`** |
| **Governance disposition** | **OWNER-ACCEPTED FOR QUALIFICATION** |
| **Empirical verification** | **REQUIRED — after a separate access authorization** |

### Documented planning boundaries

Read from first-party public documentation on 2026-08-28. **Each table's depth is cited to that
table's own page** (`PSR-SHD-125` tickers, `PSR-SHD-126` actions, `PSR-SHD-127` fundamentals,
`PSR-SHD-128` daily fundamentals), with the `stocks` conflict at `PSR-SHD-122`/`PSR-SHD-123`:

| table | documented planning boundary |
|---|---|
| `stocks` | **December 1998 onward for planning** — the conservative side of a conflict: the detailed table page states January 1998, the Prices overview states December 1998 |
| `actions` | January 1998 (`PSR-SHD-126`) |
| `fundamentals` | January 1998 (`PSR-SHD-127`) |
| `daily` | December 1998 (`PSR-SHD-128`) |
| `tickers` | June 1990 (`PSR-SHD-125`) |

**These are documented planning boundaries. They are not certified earliest actual records.** The
distinction is the whole point of recording them this way:

- **actual minimum dates must be measured from the subscribed data**, per table;
- **active and delisted coverage must be measured**, not inferred from a start date;
- **completeness must be measured per table and per relevant dimension**, not assumed uniform.

**"Full History" means the purchased full-history tier for the tables the Bundle includes.** It
does not certify record-level depth. What a tier is called and what it contains are two facts, and
only the first is public.

---

## 5. Tickers / security-master point-in-time boundary

**The `tickers` table is not assumed to provide historical point-in-time snapshots of every mutable
metadata attribute**, and one vendor statement makes that concrete rather than cautious. Sharadar
states publicly that **the exchange field is the latest primary listing venue**, and that historical
tracking of such changes is not currently provided (`PSR-SHD-124`).

Consequences:

- **Current exchange, category, delisting state, identifier and other mutable attributes must never
  be silently treated as historically known.** A current value read as a historical one is
  look-ahead wearing a schema's clothing — and it is the quiet kind, because nothing errors.
- Historical security identity and universe construction must be built from **approved permanent
  identifiers**, **corporate actions**, **price availability**, **conservative bounds** and **later
  empirical qualification** — not from a current-state metadata read.
- **Any historical attribute that is unavailable requires an explicit disposition**: a declared
  bound, an exclusion, or a profile downgrade. Never a silent substitution of today's value.

### `permaticker` — entity granularity is unresolved, and for an unusual reason

| | |
|---|---|
| **Public resolution** | **`PUBLICLY_UNRESOLVED` — CONFLICTING FIRST-PARTY DOCUMENTATION** |
| **Governance disposition** | conservative operational bounds below, pending independent resolution |

Two **current** first-party Sharadar pages describe `permaticker` at two different entity levels,
and they contradict each other directly:

| page | section | wording |
|---|---|---|
| [`/docs/tickers`](https://sharadar.com/docs/tickers) | query parameters | *"a unique and unchanging identifier for an **issuer**"* (`PSR-SHD-113`) |
| [`/docs/faqs`](https://sharadar.com/docs/faqs) | *How are ticker changes handled?* | *"Sharadar's own unchanging and unique identifier for a **security**"* (`PSR-SHD-124`) |

**Neither page overrides the other.** Both are current, both are first-party, and nothing published
adjudicates between them. **This ADR does not classify `permaticker` as either an issuer-level or a
security-level identifier**, because the public record does not support either classification.

Note how this differs from Q7. Q7 is unresolved because **no page speaks**; this is unresolved
because **two pages speak and disagree** — which is the more dangerous shape, since either statement
read alone looks like a settled answer. An earlier revision of this ADR read the FAQ alone and
recorded security-level semantics as settled. That was wrong, and the error is instructive: the
evidence for the other reading was already in the register.

**Conservative operational rule, binding until independently resolved.** Treat
`permaticker` as an **opaque, vendor-stable identifier** and nothing more:

- **preserve it exactly** as the vendor supplies it;
- **do not infer issuer identity** from it;
- **do not infer security or share-class granularity** from it;
- **do not collapse share classes or securities** using it alone;
- **do not infer issuer-level concentration or exposure groupings** from it;
- **do not use it alone to establish cross-table entity identity**.

Any issuer *or* security relationship requires **independent evidence, an explicit governed mapping,
or later empirical qualification** — and **the subscription does not authorize that qualification
yet** (§8).

**Both failure directions are real, and they fail in opposite ways.** That is why the rule refuses
to assume either granularity rather than picking the safer-sounding one — there isn't one.

*If `permaticker` is actually **security-level** and we treat it as **issuer-level**.* Several
securities or share classes of one issuer would carry **different** identifiers. Grouping by those
identifiers as though each named an issuer **fragments that issuer's exposure across several
groups**, and so can **understate issuer-level concentration** — the kind of error an issuer
exposure limit exists to catch and, computed this way, would not.

*If `permaticker` is actually **issuer-level** and we treat it as **security-level**.* Several
securities or share classes of one issuer would **share** one identifier. Using it as security
identity **collapses or conflates distinct securities**, corrupting security-level histories,
positions, returns, corporate-action handling and any join keyed on it.

**Neither error announces itself.** Both produce a table that reconciles, sums and renders exactly
as a correct one would.

This is the contract's existing rule applied to a specific vendor fact, not a new rule.

---

## 6. Price-field semantics

Sharadar states that OHLCV are split-adjusted, that `closeunadj` is unadjusted and "can be used to
impute" unadjusted Open/High/Low/Volume, and that `closeadj` is split-, cash-dividend- and
spinoff-adjusted and "can be used to impute" fully adjusted Open/High/Low (`PSR-SHD-111`,
`PSR-SHD-120`).

**Native split-adjusted OHLCV must remain distinguishable from `closeunadj` and `closeadj`.**

**Complete unadjusted OHLCV must not be assumed native merely because adjusted variants can be
reconstructed.** "Can be imputed" is a statement about arithmetic, not about what the vendor sent.

Any imputed unadjusted or fully adjusted OHLCV must be:

- **explicitly derived** — never presented as a provider field;
- **formula-versioned** — the convention that produced it is part of its identity;
- **provenance-bearing** — traceable to the exact provider bytes it came from;
- **reproducible** — the same inputs must give the same output;
- **distinguishable from exact provider bytes** at every layer.

**A derived field must never be labelled a raw exchange observation.** That mislabelling is exactly
what the point-in-time contract's origin vocabulary exists to prevent.

---

## 7. Commercial and subscription state

| | |
|---|---|
| Sharadar Personal Use **Full History Bundle** | **PURCHASED / ACTIVE FOR QUALIFICATION** |
| Billing form | **monthly** |
| Budget | within the Blueprint V3.0 §11 base annual data budget |

**What this purchase is not.** It does not select Sharadar as the production provider, it does not
close **G1**, and it does not close **G2**. **G3 remains CLOSED** under
[ADR-0008](ADR-0008-sharadar-personal-use-license-and-private-qualification.md), on the personal-use
terms recorded there — every one of which still binds, including that Services Data stays inside the
private boundary and never reaches Git, an AI session or an external LLM API.

Buying access to evaluate a provider and choosing that provider are different acts. This is the
first.

---

## 8. Authorization matrix

| | |
|---|---|
| subscription authorization | **YES** |
| purchase authorization | **YES** |
| qualification subscription purchased | **YES** |
| qualification subscription active | **YES** |
| production provider selected | **NO** |
| G1 closed | **NO** |
| production information-set profile approved | **NO** |
| G2 closed | **NO** |
| private credential retrieval / setup authorized | **NO** |
| Secrets Manager credential setup authorized | **NO** |
| provider API call authorized | **NO** |
| public test-token probing authorized | **NO** |
| Services Data access authorized | **NO** |
| Services Data ingestion authorized | **NO** |
| bulk download authorized | **NO** |
| production backfill authorized | **NO** |
| real S3 writer implemented | **NO** |
| production ingestion implemented | **NO** |
| broker or LEAN activity authorized | **NO** |
| live trading authorized | **NO** |

**The gap between the first four rows and the rest is the substance of this ADR.** A subscription
exists; nothing in this repository may yet use it.

---

## 9. Required future qualification

A **separately authorized** qualification phase must verify at minimum:

- table entitlement and manifest;
- actual earliest and latest records;
- active and delisted coverage;
- per-table row counts and minimum dates;
- fundamentals dimension coverage and point-in-time behaviour;
- actions coverage and event semantics;
- ticker / `permaticker` identity behaviour;
- ticker-change and recycled-symbol behaviour;
- mutable current-metadata leakage risks;
- stock-field adjustment semantics;
- reconstruction / imputation behaviour;
- table referential integrity;
- update and availability timing;
- deterministic bounded failure behaviour;
- the **P1–P9** provider qualification requirements
  ([implementation plan](../phase3/implementation-plan.md), ADR-0005 §G1).

**These are recorded, not performed.** None was carried out for this ADR, and none may be until a
separate written authorization exists — CLAUDE.md §8. Their results, when they exist, are private
under ADR-0008 §3 and belong in the licensed S3 `qualification/` prefix and git-ignored `.runtime/`,
never in Git.

---

## 10. Decision-gate map after this ADR

**Unchanged.** This ADR closes no gate and opens none.

| Gate | Subject | Status |
|---|---|---|
| **G1** | provider selection / qualification | **OPEN** |
| **G2** | production information-set profile | **OPEN** |
| **G3** | vendor licensing — Sharadar personal use | **CLOSED (2026-08-27, ADR-0008)** |
| **G4** | analyst estimates and revisions | **OPEN** |
| **G5** | historical borrow | **OPEN** |
| **G6** | options overlay | **OPEN** |
| **G7** | strategy-taxonomy evidence | **OPEN** |

**ADR-0005 remains PROPOSED.** Phase 3 remains **NOT COMPLETE**. Live trading remains
**HARD-DISABLED**. INC-0002 remains **OPEN**.

---

## 11. Consequences

**Positive.** Two questions stop blocking work, and stop blocking it *honestly* — each recorded in
the state the evidence actually supports rather than flattened into one:

- **Q7 is publicly unresolved**, owner-accepted for qualification, with the conservative
  classification made binding rather than quietly assumed away;
- **Q8 is publicly bounded but not empirically verified**, owner-accepted for qualification, with
  the documented depths recorded as planning boundaries and the measurement obligation recorded
  rather than skipped.

They ceased to be pre-purchase blockers for **different reasons**, and §3 and §4 keep that
difference visible. The subscription that makes empirical qualification possible now exists, and the
boundary between having access and using it is written down where a future session will read it
before acting.

**Negative, and stated plainly.** A subscription is now running with nothing in this repository able
to use it, which is a real cost against a real clock — the qualification phase it exists for is not
yet authorized.

Accepting Q7 as unresolved also means the price data's origin may *never* be established. The
consequence of that is **scoped, not global**, and §3 states the scope: if Q7 stays unresolved, the
**Sharadar price data itself** remains `PROVIDER_DERIVED`, its permitted historical profile remains
`PROVIDER_REALISTIC_PIT`, and **an artifact whose classification rests solely on that price data
cannot be `PUBLIC_PIT`**. An artifact supported by *independent* qualifying public evidence needs its
own lineage and its own classification, which **this ADR neither establishes nor prohibits**.

Stating that consequence as an unconditional, indefinite ceiling over every artifact that merely
touches this data would have been the easier sentence and the wrong one: it would refuse, in
advance, a future artifact whose public standing rests on evidence this decision never examined.

**A risk worth naming.** The most likely way this decision goes wrong is not a wrong answer but a
forgotten one: a later session, seeing an active subscription, treats access as authorized. §8
exists to make that read as the error it would be.

---

## 12. Review

Reviewed with the pull request that introduces it. Accepted on merge; until then it carries no
authority.
