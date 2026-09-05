# Feedback and self-maturation — specification

**Status: ACCEPTED SPECIFICATION EFFECTIVE ON MERGE OF PR #71, and PROPOSED until that merge —
NOT IMPLEMENTED, NOT AUTHORIZED.**

This document specifies how KalpaMani would learn from its own operation: the stages of the loop,
what each one consumes and produces, who owns it, what it may refuse, and — the part that matters
most — **exactly where a human decision is required and cannot be delegated**.

**It specifies. It does not implement, and it authorizes nothing.** No learning engine, no
attribution service, no drift detector, no research automation, no scheduler and no promotion
mechanism exists or is authorized because this document describes one.

**No alpha is claimed anywhere in this document. No result is asserted, and none exists.**

**Introduced by** [ADR-0027](../decisions/ADR-0027-cockpit-and-feedback-architecture-and-governance.md).
**Amended by** [ADR-0028](../decisions/ADR-0028-cockpit-contract-completion-and-boundary-corrections.md) — §2.7 only.
ADR-0028 is **PROPOSED and carries no authority while the pull request introducing it is open**,
and the correction it makes here is proposed with it.
**Builds on** [ADR-0006](../decisions/ADR-0006-adopt-blueprint-v3-and-strategy-brain-governance.md)
§C and [ADR-0026](../decisions/ADR-0026-strategy-brain-architecture-and-governance.md)'s
[Brain specification](../phase4/strategy-brain-specification.md) §12, §13, §22 and §25 —
**consumed unchanged, and neither amended nor superseded**.

---

## 1. The loop

```text
Signal / Trade / Decision Journal
    -> Outcome and Attribution
        -> Strategy Health / Drift / Failure Clusters
            -> Research Queue
                -> Preregistered Hypothesis
                    -> Immutable Challenger
                        -> Authorized Backtest / Locked OOS / Stress
                            -> Shadow
                                -> Governance Packet
                                    -> Human-Authorized Release
```

**Ten stages, and the tenth is a person.** Everything before it may eventually run without a human
in the loop, within separately approved bounds. **The tenth may not, ever.**

**The loop is scientific, not adaptive.** An adaptive system adjusts itself toward recent outcomes;
this one forms a hypothesis, registers it before looking, tests it against locked data, and asks a
human. The difference is the difference between learning and curve-fitting at production speed.

---

## 2. Stage contracts

Each stage states its **inputs**, **outputs**, **owner**, **version pins**, **entry
prerequisites**, **exit transitions**, **refusal reasons** and **audit references**. Refusal reasons
are closed vocabularies; **a stage that cannot proceed says why in a code, never in prose**.

### 2.1 Journal

| | |
|---|---|
| **Inputs** | every candidate decision, trade event, risk decision, order and fill event, and safety action, as recorded by the subsystem that owns it |
| **Outputs** | an immutable, append-only journal keyed by decision and trade identity |
| **Owner** | each producing subsystem writes its own records; the journal aggregates references |
| **Pins** | strategy, factor-definition, risk-policy, entry-policy, exit-policy, model, prompt and code identities on every record |
| **Prerequisites** | none — journaling is unconditional |
| **Transitions** | records become available to attribution once their trade or decision reaches a terminal or measurable state |
| **Refusals** | `UNPINNED_VERSION`, `SCHEMA_MISMATCH`, `MISSING_LINEAGE` |
| **Audit** | the journal **is** the primary audit input |

**Provider payload bytes are never written to the journal** — ADR-0026's Brain specification §27,
applied unchanged. Licensed rows stay inside the private boundary; the journal carries **references
and lineage identifiers**, and a reference is not a row.

### 2.2 Outcome and attribution

| | |
|---|---|
| **Inputs** | journaled decisions and trades, realized economics, benchmark and regime series |
| **Outputs** | per-trade and per-module attribution — strategy, factor, regime, execution and cost components |
| **Owner** | the attribution component of the future research engine |
| **Pins** | the metric dictionary version, plus every pin the journal record carries |
| **Prerequisites** | a terminal or measurable trade state; a complete-enough price path |
| **Transitions** | provisional attribution on close; **final** attribution when every input is settled, recorded as its own event |
| **Refusals** | `INCOMPLETE_PRICE_PATH`, `INSUFFICIENT_OBSERVATIONS`, `UNRESOLVED_CORPORATE_ACTION`, `COST_TREATMENT_UNKNOWN` |
| **Audit** | attribution records reference the journal records they explain |

**Provisional attribution is labelled provisional.** A number that may still change is not a
finding, and finalization is an event rather than a quiet overwrite.

### 2.3 Strategy health, drift and failure clusters

| | |
|---|---|
| **Inputs** | attribution, the health inputs ADR-0026's Brain specification §13 names, execution quality, capacity, correlation, regime and incident records |
| **Outputs** | health-state transitions with reasons; drift measurements; **failure clusters** — groups of losses sharing a cause rather than a period |
| **Owner** | the health monitor |
| **Pins** | strategy version, factor-definition version, metric dictionary version |
| **Prerequisites** | the minimum observations the health contract declares |
| **Transitions** | ADR-0026's Brain specification §13 state machine, unchanged: `HEALTHY`, `WATCH`, `DEGRADED`, `NEW_ENTRIES_REDUCED`, `NEW_ENTRIES_DISABLED`, `SUSPENDED`, `RETIRED` |
| **Refusals** | `INSUFFICIENT_OBSERVATIONS`, `MISSING_ATTRIBUTION`, `STALE_INPUT` |
| **Audit** | every transition records its inputs, its rule and its authority |

**Reducing or disabling new entries is automatic. Restoring them is not, and recovery past a
governed suspension is never automatic.** **A degradation creates a research queue entry; it does
not mutate a strategy parameter.** There is **no last-ten-trades threshold optimization in place**,
and none may be added by an implementation.

### 2.4 Research queue

| | |
|---|---|
| **Inputs** | health transitions, drift, failure clusters, missed-opportunity patterns, overlap findings, human-entered questions |
| **Outputs** | prioritized queue items, each naming its trigger, its issue, its proposed experiment, its baseline and the authorizations it needs |
| **Owner** | the research queue |
| **Pins** | the triggering evidence identities |
| **Prerequisites** | a stated trigger and a named baseline candidate |
| **Transitions** | `QUEUED` → `PREREGISTRATION_DRAFTED` → `REGISTERED`, or `WITHDRAWN` with a reason |
| **Refusals** | `NO_NAMED_BASELINE`, `DUPLICATE_OF_OPEN_ITEM`, `DEPENDENCY_UNAUTHORIZED`, `DATA_UNAVAILABLE` |
| **Audit** | queue items reference the health or attribution evidence that produced them |

**A queue entry is not an authorization.** Generating and prioritizing research is inside the
automation's approved bounds; running it against real data is a separate gate, and every item
displays the authorization it is waiting on.

### 2.5 Preregistered hypothesis

| | |
|---|---|
| **Inputs** | a queue item and its evidence |
| **Outputs** | an **immutable** registration: identity, registration time, trigger, strategy, thesis, baseline, variation, **trial budget**, **declared evaluation class**, **research lineage**, success criteria, failure criteria, data requirements, research version |
| **Owner** | the hypothesis registry |
| **Pins** | data manifest, information-set profile, revision view, factor-definition version, research code identity |
| **Prerequisites** | success **and** failure criteria stated **before** any result is seen |
| **Transitions** | `REGISTERED` → `AMENDED` (linked) or `SUPERSEDED_BY_NEW_REGISTRATION`; results attach as **linked records** |
| **Refusals** | `CRITERIA_INCOMPLETE`, `NO_FAILURE_CRITERION`, `BUDGET_EXHAUSTED`, `BUDGET_EXHAUSTED_ACROSS_LINEAGE`, `DATA_REQUIREMENT_UNAVAILABLE` |
| **Audit** | the registration is itself an immutable audit record |

**Preregistration is immutable.** A design change creates a **linked amendment or a new
registration, before additional research**, and results and decisions **append** rather than edit:
later records attach to a registration and **never edit the preregistration**.
A registry that let a hypothesis be edited after a result is a registry that records what the
researcher wishes they had predicted.

**A failure criterion is mandatory.** A hypothesis that cannot fail has not been stated.

### 2.6 Immutable challenger

| | |
|---|---|
| **Inputs** | a registration, a Champion version, a variation definition |
| **Outputs** | an immutable Challenger strategy version |
| **Owner** | the strategy version registry |
| **Pins** | every version identity ADR-0026's Brain specification §9 requires |
| **Prerequisites** | a registered hypothesis; an authorized environment set that **excludes** order-producing stages |
| **Transitions** | ADR-0026's Brain specification §10 lifecycle stages, advanced only with the evidence and authority each requires |
| **Refusals** | `UNPINNED_VERSION`, `NO_REGISTRATION`, `UNAUTHORIZED_ENVIRONMENT` |
| **Audit** | version creation, activation, retirement, promotion and rollback are all recorded |

**A modification creates a new Challenger version; it is never an edit in place**, and **an open
position stays governed by the exact versions that opened it**.

### 2.7 Authorized backtest, locked out-of-sample and stress

| | |
|---|---|
| **Inputs** | a Challenger, a registration, an immutable research manifest |
| **Outputs** | run results, trial-count increments, decomposition by regime, sector and factor, capacity analysis, stress results |
| **Owner** | the research runner |
| **Pins** | manifest, profile, revision view, code and configuration identity, metric dictionary version |
| **Prerequisites** | ADR-0026's Brain specification §22 methodology standards, and **a named baseline first** |
| **Transitions** | `PLANNED` → `RUNNING` → `COMPLETED` / `FAILED` / `ABANDONED`; every terminal state **counts against the trial budget** |
| **Refusals** | `BUDGET_EXHAUSTED`, `OUT_OF_SAMPLE_ALREADY_CONSUMED`, `EXPOSURE_HISTORY_UNKNOWN`, `RELATED_LINEAGE_EXPOSED`, `BUDGET_EXHAUSTED_ACROSS_LINEAGE`, `REUSE_METHODOLOGY_UNAUTHORIZED`, `REPRODUCTION_MISMATCH`, `MANIFEST_UNAVAILABLE`, `LEAKAGE_RISK_DETECTED`, `AUTHORIZATION_MISSING` |
| **Audit** | every run, including failed and abandoned runs, is recorded against its registration |

**All trials are tracked, including failed and abandoned runs.** A multiple-testing control whose
denominator is whatever the researcher recalls is not a control, and a run that is quietly discarded
is the one that most needs counting.

**Leakage and out-of-sample reuse protections, as requirements:**

| | |
|---|---|
| **the locked set is locked** | out-of-sample data is consumed **once per locked set**, and **not once per registration**. Exposure is recorded against the **locked set**, and **a new hypothesis, registration or Challenger identity does not make exposed data untouched again** |
| **exposure is tracked, not reset** | §2.7.1 holds the exposure ledger, the lineage rule, the three evaluation classes and their refusals |
| **purging and embargo** | overlapping-horizon research purges and embargoes around the evaluation boundary; the parameters are recorded, not assumed |
| **no peeking through selection** | universe construction, feature selection and parameter neighbourhoods are declared before the locked evaluation, not tuned against it |
| **point-in-time only** | every input resolves as of the decision instant, through the declared revision view. **No "latest" shortcut** |
| **survivorship awareness** | the universe is historical membership, never today's list |
| **reproducibility evidence** | a run records manifest, profile, revision view, code identity, configuration identity, random seeds and environment, sufficient to reproduce it **without a network** |

#### 2.7.1 Out-of-sample exposure is tracked across registrations

**A registration identity is not a reset button.** The earlier rule — a second evaluation against the
same locked set requires a new registration — made re-registration the price of reuse, and
re-registration is free. **A new hypothesis, a new registration and a new Challenger identity leave
the data exactly as exposed as it was**, and a control that a rename defeats is not a control.

**The exposure ledger is keyed by the locked set.**

| | |
|---|---|
| **identity** | every locked set has a **locked-set identity** derived from its manifest, its information-set profile, its revision view and its evaluation boundary. **Two sets with the same identity are the same set**, whatever they are called |
| **the ledger** | an append-only record **attached to the locked set**, not to a registration. Every evaluation that touches it appends an entry |
| **each entry records** | the registration identity · the Challenger identity · the research code and configuration identity · the evaluation class · the instant · the requested extent · **the overlap with every prior entry** |
| **it is read across lineage** | a registration reads the whole ledger for the sets it names, including entries written under **other** registrations |

**Related research lineage counts as exposure.** Exposure follows the research, not the label. A
registration inherits every ledger entry reachable through its **parent registration**, its
**amendment chain**, the registration it **supersedes or was superseded by**, a **shared named
baseline**, a **shared queue trigger or failure cluster**, and a **shared Challenger derivation**.
**A derived experiment does not get a clean set because it was given a new name.**

**Unknown exposure history cannot support a fresh out-of-sample claim.** If the ledger is missing,
incomplete, unresolvable, or cannot be shown to cover every prior evaluation of the set, the state
is `EXPOSURE_HISTORY_UNKNOWN` and **a confirmatory evaluation is refused**. **An absence of recorded
exposure is not evidence of absent exposure**, and it is never read as one.

**Trial budgets and multiple-testing records do not reset through renaming.** Both are read across
the lineage above. A registration whose lineage has exhausted its budget is `BUDGET_EXHAUSTED`
**even on its first run of its own**, and **failed and abandoned runs count wherever they occurred**.

**Three evaluation classes, and only one of them is confirmation.**

| Class | What it is | What it may claim |
|---|---|---|
| `DETERMINISTIC_REPRODUCTION` | re-executing a **frozen** prior run at its exact manifest, profile, revision view, code identity, configuration identity, seeds and environment, and reproducing its recorded results | **no new confirmation of anything.** It confirms reproducibility and nothing else. It adds **no** new exposure entry beyond a reproduction note, and it **does not** consume trial budget |
| `EXPLORATORY_REUSE` | any further look at data the ledger already records as exposed | **disclosed, and never presented as fresh out-of-sample.** It appends an exposure entry, it **consumes trial budget**, and every downstream comparison, packet and report **carries the disclosure** |
| `CONFIRMATORY` | eligible **only** against an untouched holdout, or new forward evidence generated after the exposure, or under a **separately governed methodology that explicitly accounts for the reuse** | the **only** class that may be described as out-of-sample confirmation, and only within the limits its methodology states |

**The class is declared in the registration and checked against the ledger before the run starts.**
A run that declares `CONFIRMATORY` against a set the ledger shows as exposed is **refused**, not
downgraded silently — although the researcher may re-declare it as `EXPLORATORY_REUSE` and proceed
with the disclosure that entails.

**Refusals, closed:**

```text
OUT_OF_SAMPLE_ALREADY_CONSUMED     the ledger records prior exposure of this locked set
EXPOSURE_HISTORY_UNKNOWN           the ledger cannot be shown to be complete
RELATED_LINEAGE_EXPOSED            a related registration exposed this set
BUDGET_EXHAUSTED_ACROSS_LINEAGE    the lineage budget is spent, whatever this identity's own
                                   count says
REUSE_METHODOLOGY_UNAUTHORIZED     a reuse-accounting methodology was claimed and is not
                                   separately governed and authorized
REPRODUCTION_MISMATCH              a declared deterministic reproduction did not reproduce
```

**What is preserved unchanged.** **Preregistration stays immutable**, results and decisions still
**append** as linked records, **failed and abandoned trials are still retained and still count**,
and a design change still creates a **linked amendment or a new registration before additional
research**. **None of that is relaxed here** — what changes is that the new registration inherits
the exposure rather than escaping it.

**The negative control this rule exists for.** *A new registration identity, a new Challenger
identity and a new research question, evaluated against a holdout the ledger already records as
exposed, is refused with `OUT_OF_SAMPLE_ALREADY_CONSUMED` — and is not admitted as fresh
out-of-sample evidence under any name.* That case is a required test of any implementation.

### 2.8 Shadow

| | |
|---|---|
| **Inputs** | an immutable Challenger, the live point-in-time opportunity set |
| **Outputs** | shadow decisions, overlap and divergence against the Champion, hypothetical economics with stated slippage and capacity assumptions |
| **Owner** | the shadow runner |
| **Pins** | Challenger version and every pin it carries |
| **Prerequisites** | completed locked out-of-sample evaluation; an authorization for shadow operation |
| **Transitions** | `SHADOW_RUNNING` → `SHADOW_COMPLETE` / `SHADOW_HALTED` |
| **Refusals** | `NO_OOS_EVIDENCE`, `AUTHORIZATION_MISSING`, `DATA_UNAVAILABLE` |
| **Audit** | shadow decisions are journaled exactly as production decisions are, and labelled `SHADOW` |

**Shadow produces no order, in any environment.** A shadow result is hypothetical economics with
stated assumptions, and it is never presented in a series with realized results.

### 2.9 Governance packet

| | |
|---|---|
| **Inputs** | registration, all runs against it, locked out-of-sample and stress results, **the exposure ledger of every locked set the evidence rests on**, shadow evidence, Champion comparison, exposure and operational impact |
| **Outputs** | an assembled packet: proposal, cause, evidence, risk, factor and operational impact, failure modes, comparison, **the evaluation class and exposure disclosure of every result it cites**, **recommendation**, and a place for the human decision |
| **Owner** | the governance packet assembler |
| **Pins** | every version and manifest identity referenced |
| **Prerequisites** | complete evidence for every claim the packet makes |
| **Transitions** | `ASSEMBLING` → `READY_FOR_HUMAN_REVIEW`; and no further transition is automatic |
| **Refusals** | `EVIDENCE_INCOMPLETE`, `TRIAL_COUNT_UNRECORDED`, `NO_BASELINE_COMPARISON`, `CRITERIA_NOT_EVALUATED`, `EXPOSURE_DISCLOSURE_INCOMPLETE` |
| **Audit** | the packet is immutable once ready, and the decision attaches to it |

**A recommendation is input to a human decision, never the decision.** **`READY_FOR_HUMAN_REVIEW`
is not an approval**, and the automation's authority ends exactly here.

### 2.10 Human-authorized release

| | |
|---|---|
| **Inputs** | a ready packet |
| **Outputs** | a recorded human decision — approve, reject, or request more evidence — with authority, time and reasoning |
| **Owner** | **a human**, through the separately governed decision path that owns approvals |
| **Prerequisites** | a complete packet |
| **Transitions** | on approval, the promotion the packet requested, executed by the deterministic mechanism that owns it |
| **Refusals** | a human may refuse for any reason, and the reason is recorded |
| **Audit** | the decision record is immutable and is linked to the packet and to every version it affects |

**The Cockpit displays this decision. It does not originate it in V1.**

---

## 3. The authority matrix

### 3.1 Automatic, within separately approved bounds

```text
monitor and diagnose
detect drift, overlap, failure clusters and missed-opportunity patterns
generate research ideas and preregister experiments
run authorized-scope research
operate authorized shadow Challengers
prepare governance packets
invoke ONLY preapproved deterministic safety logic
fail closed
```

**"Within separately approved bounds" is load-bearing.** Each capability above requires its own
authorization before it may run at all; listing it here specifies what such an authorization *could*
cover, and grants none.

### 3.2 Human approval required, and not delegable

```text
promotion into order-producing Paper operation
Paper -> Micro-Live
Micro-Live -> scaled operation
production model or parameter replacement
capital increase
risk increase
leverage
short-exposure increase
provider purchase, licence, or a new production dependency
resumption after a governed suspension
any change to kill-switch behaviour
```

**Self-maturing is not self-governing.** The system may prepare, evidence and recommend every item
in this list. **It may take none of them.**

### 3.3 The things no implementation may add

| | |
|---|---|
| **no automatic production parameter mutation** | not on drawdown, not on a losing streak, not on drift, not on a research result |
| **no last-ten-trades threshold optimization in place** | reparameterizing against recent outcomes is curve-fitting performed by a machine at production speed |
| **the Champion is unchanged until an authorized promotion** | a Challenger that outperforms is a Challenger that outperforms |
| **open positions stay pinned** | strategy, factor-definition, risk-policy, entry-policy and exit-policy versions may not mutate under an open position |
| **no self-promotion** | no stage advances itself past shadow |
| **no threshold from a synthetic example** | **no numerical research or safety threshold becomes a production rule merely because it appears in a synthetic example** in this repository |

---

## 4. Writes and reads are different systems

| | |
|---|---|
| **the learning engine** | consumes journal and attribution records, produces queue items, registrations, Challenger versions, run results, shadow evidence and packets. **It writes.** It does not exist |
| **the Cockpit** | reads projections of all of the above and displays them. **It writes nothing**, advances no stage, and originates no approval. It does not exist either |

**Neither is implemented by this cycle, and the separation is specified now so that a later
implementation cannot quietly merge them.** A Cockpit that could advance a stage would be a control
plane, and a control plane needs the authentication, authorization, audit, idempotency and safety
architecture that Cockpit V1 explicitly does not have.

---

## 5. What this document does not do

```text
implements NOTHING                        authorizes NOTHING
runs no research                          runs no backtest
creates no module under src/              creates no scheduler
promotes nothing                          approves nothing
reads no provider data                    reads no private artifact
claims no alpha                           asserts no result
establishes no threshold                  changes no risk or capital value
```

| | |
|---|---|
| Feedback specification | **ACCEPTED EFFECTIVE ON MERGE OF PR #71** |
| Learning-engine implementation | **NOT STARTED / NOT AUTHORIZED** |
| Research automation | **NOT STARTED / NOT AUTHORIZED** |
| Backtesting | **NOT STARTED** |
| P1–P9 | **UNEVALUATED** |
| G1 / G2 | **OPEN / OPEN** |
| Provider selected | **NONE** |
| Phase 3 | **NOT COMPLETE** |
| Live trading | **HARD-DISABLED** |

**Specification, implementation, research, deployment and execution are five separate gates.**
