# ADR-0034 — Select Sharadar for the initial equity-research domains (a partial G1 decision)

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0034 is proposed and carries no authority.
That is a statement about the present, it will remain true of these days after any later merge, and it
is not to be rewritten as though this decision had authority before it was accepted. On merge, this ADR
becomes **ACCEPTED / IN FORCE** as **a recorded owner decision on gate G1, for the domains it names, and
nothing else**.

**The condition above has since been satisfied.** **PR #92 merged** — merged **2026-09-12T03:45:17Z**, merge
commit **`aa2ca41176e954bdebd4ded3e55347324a8f3215`**, ordered parents **`a8e23cfe8b97e9f683c40c429137019f1cbb0cd0`** then
**`ced38e5fbe21d5bd03bcd5ac214de6127a35cd3a`**, with a **merge tree identical to the independently reviewed pull-request head
tree** (`56ac0a3ad49f7159c32c908c8ad457bd5b25ddb9`). ADR-0034 is therefore **ACCEPTED / IN FORCE**, together with
[ADR-0035](ADR-0035-initial-breakout-long-research-dataset-ingestion-design.md) on the same merge. While the
pull request was open it was proposed and carried no authority — true then, and not rewritten.

**Nothing was run to produce this decision.** No AWS CLI or SDK call, no STS, SSO or Secrets Manager
call, no S3 operation, no Terraform command, no provider request, no acquisition, no assessment, no
private-report retrieval by any automated or AI-assisted process, no backtest and no broker activity. The
owner's private review of the combined report — ADR-0018 §14.1 gate 12 — was an owner-only act whose
contents are not recorded here.

**Accepting this ADR authorizes no execution.** It authorizes no ingestion, backfill or update, no
provider request, no credential use, no infrastructure mutation, no backtest, no Brain implementation,
no CONTROL publication and no trading. **A provider-selection decision, an information-set-profile
decision, an ingestion design, and an ingestion authorization are four separate gates**, and this
decision closes only the first, and only in part.

**This ADR and [ADR-0035](ADR-0035-initial-breakout-long-research-dataset-ingestion-design.md) are
proposed on one pull request and become effective together on its single independently reviewed merge.**
ADR-0035 depends on this decision; this decision does not depend on ADR-0035. Neither is in force before
that merge.

---

## 1. Context

The bounded private empirical qualification package accepted by
[ADR-0018](ADR-0018-bounded-private-empirical-sharadar-qualification.md) — as amended by
[ADR-0019](ADR-0019-write-only-acquisition-collision-policy.md) and
[ADR-0020](ADR-0020-request-scoped-qualification-payload-identity.md), under the principal model of
[ADR-0021](ADR-0021-qualification-runtime-principal-and-trust-model.md) and
[ADR-0022](ADR-0022-qualification-permission-set-name-limit.md), and the private bindings of
[ADR-0023](ADR-0023-private-runtime-binding-for-the-licensed-bucket.md),
[ADR-0024](ADR-0024-governed-qualification-environment-binding-source.md) and
[ADR-0025](ADR-0025-private-runtime-binding-for-the-combined-assessment.md) — has been executed to
its end:

| Step | Outcome | Date (UTC) |
|---|---|---|
| Run A acquisition | `COMPLETED`, 48 provider requests, 145 append-only licensed writes | 2026-09-04 |
| Run B acquisition | `COMPLETED`, 48 provider requests, 145 append-only licensed writes; provider budget 96 of 96 consumed | 2026-09-12 |
| Combined assessment, first invocation | `REFUSED_LOCATOR` (exit 9) before any acquisition-record or payload read and before any write — a wrong Run B identity, established offline | 2026-09-12 |
| Combined assessment, second invocation | `COMPLETED`; 194 object-byte reads, one owner-only private report published | 2026-09-12 |
| Private owner review (gate 12) | performed by the owner; contents never recorded | 2026-09-12 |

Those are command outcomes. The **P1–P9 results exist inside the private report and are not recorded in
this repository**: [ADR-0008](ADR-0008-sharadar-personal-use-license-and-private-qualification.md) and
ADR-0018 §11.3 keep the report out of Git, CI, logs, chat, automated AI sessions and CONTROL, and the report
carries, by design, no aggregate verdict, no provider-selection value and no readiness value. **The
disclosure history is wider than the repository, and it is recorded rather than denied**: the owner, as
licensee, separately authorized sharing the assessment output with an external AI service to obtain
recommendations. This ADR records neither that output nor those recommendations, and it makes no claim
either way about whether that sharing is within the vendor's Terms; that is not established here. **G1 — provider selection, "which vendors,
for which domains" ([ADR-0005](ADR-0005-point-in-time-data-architecture.md) gate table) — is an owner
decision taken by a person reading that evidence.** This ADR records that decision in **decision language
only**. It states what was selected, for what, under what restrictions, and what remains open. It states
no reason that would disclose an evaluative conclusion about the provider's data, because Sharadar Terms
§8 bars disclosing such conclusions and ADR-0008 records the owner's acceptance of that boundary.

Three facts from **public** documentation, already recorded in the provider-source register, shape the
restrictions below and may be stated:

- the `actions` table carries a single `date` and **no announcement or declaration date** (`PSR-SHD-094`,
  `PSR-SHD-112`), so announcement timing is not obtainable from it;
- the meaning of `value`, `contraticker` and `contraname` per action type — spinoffs included — **is not
  documented** (`PSR-SHD-112`);
- Sharadar price bars are classified **`PROVIDER_DERIVED`** under
  [ADR-0010](ADR-0010-accept-bounded-sharadar-semantics-and-authorize-qualification-subscription.md)
  (Q7 publicly unresolved), so they are **ineligible under `PUBLIC_PIT`** by the profile-eligibility rule
  of the point-in-time contract §3.1, and only `PROVIDER_REALISTIC_PIT` or `FORWARD_SYSTEM` can serve them.

---

## 2. Decision

### 2.1 Selected — `tickers` and `stocks`, for initial equity research

**Sharadar is selected as the provider for two domains, for initial equity research:**

| Domain | Sharadar table | Role in the research data plane |
|---|---|---|
| **security master and identity** | `tickers` | the security master; `permaticker` is the join key and the basis of `security_id`; `ticker` is a current symbol, never an identity |
| **daily price bars** | `stocks` | end-of-day OHLCV, unadjusted close and the vendor's adjusted closes, `PROVIDER_DERIVED`, `PROVIDER_REALISTIC_PIT` only |

"Initial equity research" means research datasets and research-time backtests for the Strategy Brain's
first research modules, beginning with Breakout Long. It does not mean the live data plane, and it does
not mean any dataset that informs capital before G2 closes.

### 2.2 Selected with restricted use — `actions`

**Sharadar `actions` is selected, and its use is restricted to what its delivered schema can support.**

| Use | Disposition |
|---|---|
| listing lifecycle facts — listed, delisted, delist reason, ticker change — for identity resolution and historical-universe construction | **permitted** |
| split and reverse-split facts, keyed to the ex-date, for price adjustment under `AdjustmentPolicy.SPLIT_ONLY` | **permitted** |
| cash-dividend facts, recorded as facts | **permitted as facts**; dividend adjustment is not applied in the initial dataset |
| **any announcement-based signal or feature** — anything that uses *when* an action became known | **GATED** — no announcement date exists in the delivered schema; a later decision may lift this only on evidence from an additional source |
| **spinoff treatment** — adjustment, reconstruction or any derived quantity depending on the vendor's spinoff semantics | **GATED** — the per-type meaning of `value`, `contraticker` and `contraname` is undocumented; the ingestion design must record spinoff events as facts and must exclude or flag affected securities in affected windows, never adjust for them |
| merger and acquisition counterparties, rights, other action types | **recorded as facts, not consumed**, until a later decision |

### 2.3 G2 stays OPEN; `PROVIDER_REALISTIC_PIT` is the target profile

**G2 — the production information-set profile — is not closed by this decision.** The target profile
for any dataset that will inform capital is **`PROVIDER_REALISTIC_PIT`**, and it is a target only:
closing G2 requires the documented per-dataset availability rules and the acceptance criteria that
[ADR-0035](ADR-0035-initial-breakout-long-research-dataset-ingestion-design.md) proposes, and a
separate written owner acceptance. `PUBLIC_PIT` is not a candidate for Sharadar price bars, for the
eligibility reason stated in §1. `FORWARD_SYSTEM` describes what KalpaMani actually held and exists
only once the system runs.

### 2.4 Not selected — every other domain

G1 stays **OPEN** for fundamentals, filings, events and earnings timing, estimates and revisions (G4),
borrow history (G5), options (G6), funds, insiders, holdings and any other domain. Nothing here selects a
provider for them, and nothing here rejects Sharadar for them.

### 2.5 Licence and subscription — unchanged, and owner-side

G3 stays **CLOSED** for Sharadar personal use ([ADR-0008](ADR-0008-sharadar-personal-use-license-and-private-qualification.md)).
The subscription purchased under ADR-0010 was bounded to qualification; whether a production
subscription or renewal exists is the owner's affair and is not recorded here. **This ADR authorizes no
credential use and no provider request.**

### 2.6 What this decision does not do

It records no evaluative finding, no P-test status, no measurement, no subject, no identifier and no
report content, and none may be added to it. It does not make any acquired data available to research: the
licensed material remains inside the deletion-first licensed store under the cloud-deletion runbook's
obligations, with no research-read surface. It does not authorize ADR-0035's ingestion; it makes ADR-0035
proposable.

---

## 3. Consequences

- **ADR-0005 authorization A3 — ingestion implementation for the selected domains — becomes proposable.**
  ADR-0035 is that proposal; it is proposed on the same pull request, becomes effective together with this
  decision on that single independently reviewed merge, depends on this decision, and its execution stays a
  separate authorization behind its acceptance criteria.
- **Phase 3A's provider question is answered for the three tables the qualification package acquired**,
  and for those tables only. Phase 3 stays **NOT COMPLETE**; 3B, 3C and 3D are unstarted.
- **The private report is not recorded in this repository.** A future reader of this ADR learns the
  decision and its restrictions, not the evidence. The owner's separately authorized sharing of the
  assessment output with an external AI service is part of the disclosure history and is recorded in the
  status documents without its contents; nothing here claims that sharing to be within or outside the
  vendor's Terms.
- **The restrictions in §2.2 are load-bearing for the Brain specification.** A Breakout Long research
  module may consume ex-date-keyed splits and listing lifecycle facts; it may not consume an announcement
  signal derived from `actions`, and its adjusted series may not depend on spinoff semantics.
- **Reversal is a new ADR.** If the owner later rejects Sharadar for a selected domain, G1 reopens for
  that domain and G3 reopens for any replacement provider.
- **The provider-source register is unchanged.** Public documentation facts remain where they were
  recorded; this ADR cites them and adds none.

---

## 4. Rejected alternatives

- **Select Sharadar for every domain it offers.** Rejected: only three tables were qualified, and the
  fundamentals, events and estimates surfaces carry documented limitations (P6–P8 deferred by ADR-0018)
  that were not tested.
- **Reject Sharadar and restart provider selection.** Rejected by the owner's decision; the reasons are
  evaluation information and are not recorded.
- **Hold G1 pending more evidence.** Rejected: the ADR-0018 provider budget (96 requests) is spent, and a
  further qualification package would be a new architecture decision with its own cost and its own
  authorization; the owner chose to decide on the evidence held.
- **Select `actions` without restriction.** Rejected: the delivered schema has no announcement date and
  no documented spinoff semantics, so unrestricted use would let an undocumented field drive a signal.
- **Close G2 in the same decision.** Rejected: G2 needs availability rules that do not yet exist in
  reviewable form, and a profile decision taken without them would be a label, not a control.
- **Adopt `PUBLIC_PIT` for the price domain.** Rejected on eligibility: `PROVIDER_DERIVED` facts cannot
  be served under `PUBLIC_PIT` (contract §3.1), and relabelling would be the profile mixing the contract
  forbids.
- **Record the evaluative reasons in the ADR "for reviewability".** Rejected: Sharadar Terms §8 and
  ADR-0008 bar disclosing fitness conclusions; the reviewable object is the decision and its restrictions.

---

## 5. Status of everything else

```text
G1 — tickers, stocks:                         DECIDED IN THIS ADR — in force only on merge
G1 — actions:                                 DECIDED WITH RESTRICTED USE — announcement-based signals GATED, spinoff treatment GATED
G1 — every other domain:                      OPEN
G2:                                           OPEN — target PROVIDER_REALISTIC_PIT; criteria in ADR-0035
G3:                                           CLOSED (ADR-0008) — unchanged
G4 / G5 / G6 / G7:                            OPEN — unchanged
ingestion design:                             ADR-0035 — proposed on the same pull request, dependent on this decision
production ingestion / backfill / update:     NOT AUTHORIZED / NOT RUN
research-read surface on the licensed store:  NONE — to be designed under ADR-0035, deployed under a later gate
Run A / Run B / combined assessment:          COMPLETED — command outcomes; no retry authorized; budget spent
P1-P9:                                        IN THE PRIVATE REPORT — NOT RECORDED IN THIS REPOSITORY
backtesting:                                  NOT STARTED
Brain implementation:                         NOT AUTHORIZED
Phase 3:                                      NOT COMPLETE
CONTROL:                                      DEFERRED
live trading:                                 HARD-DISABLED
```

**This ADR supersedes no earlier decision and amends no earlier ADR document.** It records the gate
decision ADR-0005 reserved for the owner, for the domains it names, and leaves every other gate exactly
where it was.
