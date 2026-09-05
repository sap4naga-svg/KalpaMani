# ADR-0026 — Strategy Brain architecture and governance

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0026 is proposed and carries no authority.
That is a statement about the present, it will remain true of these days after any later merge, and
it is not to be rewritten as though this decision had authority before it was accepted. On merge,
this ADR becomes **ACCEPTED / IN FORCE** as **architecture, contracts, governance and future
implementation boundaries** — and nothing else.

**Date:** 2026-09-05
**Supersedes:** nothing
**Superseded by:** —
**Relates to:** [ADR-0001](ADR-0001-system-foundation.md),
[ADR-0002](ADR-0002-broker-adapter-and-brokerage-boundary.md),
[ADR-0004](ADR-0004-deterministic-order-identity-idempotency-and-execution-lifecycle.md),
[ADR-0005](ADR-0005-point-in-time-data-architecture.md),
[ADR-0006](ADR-0006-adopt-blueprint-v3-and-strategy-brain-governance.md)

**Nothing was run to produce this decision.** No AWS, STS, SSO, IAM, Secrets Manager or S3 call; no
Terraform command of any kind; no Terraform state, backend configuration, `.tfvars` or `.terraform/`
read; no `.runtime/` inspection; no provider request; no credential access; no Run A retry, Run B or
combined assessment; no P1–P9 execution; no backtest; and no broker, LEAN or IBKR activity. **No
Blueprint PDF was opened.** This decision is authored from tracked repository authority alone.

---

## 1. Context

[ADR-0006](ADR-0006-adopt-blueprint-v3-and-strategy-brain-governance.md) adopted Blueprint V3.0 and,
with it, three things about the future Strategy Brain: a **six-concept taxonomy** (§D), a
**`CandidateIntent` output boundary** (§E), and a **self-maturing but not self-governing authority
split** (§C). Those are decided and in force, and this decision does not reopen them.

What ADR-0006 deliberately did **not** provide is the level of detail an implementer would need. Its
§E lists what `CandidateIntent` may and may not carry in one paragraph each; it names no decision
states, no compiler ordering, no lifecycle, no health machine, no consolidation rule, no
point-in-time gate and no research standard. **A later implementation slice starting from ADR-0006
alone would have to invent all of that**, and inventing it inside an implementation pull request is
exactly how an architectural boundary gets decided by whoever happened to be typing.

The repository has repeatedly held that **implementation, infrastructure and execution are separate
gates**. This decision applies the same discipline one step earlier: **specification is its own
gate, and it comes before implementation.**

**The timing is deliberate and the dependency is stated.** Provider qualification is incomplete —
**P1–P9 UNEVALUATED**, **data correctness and quality NOT ESTABLISHED**, **G1 and G2 OPEN**, **no
provider selected**, **Run B NOT RUN / NOT AUTHORIZED** with an earliest approved target of
2026-09-12, and **the combined assessment NOT RUN / NOT AUTHORIZED**. Specifying contracts does not
require data and produces no dependency on any; **implementing or researching against them does**,
and that is why implementation stays gated behind qualification rather than beside it.

---

## 2. Decision

**Adopt [`docs/phase4/strategy-brain-specification.md`](../phase4/strategy-brain-specification.md)
as the authoritative repository specification for the future KalpaMani Strategy Brain.**

The specification defines, in checkable form:

| | |
|---|---|
| **the locked boundary** | the Brain produces **no broker order and no position size**; its terminal output is a deterministic typed `CandidateIntent` |
| **required Brain properties** | point-in-time · deterministic at the decision boundary · versioned · reproducible · explainable · auditable · fail-closed · strategy-aware · portfolio-unaware for sizing · incapable of silently changing its own production rules |
| **the taxonomy** | alpha family · strategy module · trade template · feature · filter · risk overlay — six non-interchangeable concepts, refining ADR-0006 §D |
| **the initial families** | Momentum Continuation (Breakout Long, Pullback Long, one family cap) · Event / Information Drift (PEAD Long, PEAD Short) · Fundamental Deterioration (Deterioration Short) |
| **the point-in-time reality gate** | the Brain's first stage; no default profile, no default as-of, no "latest" shortcut, and missing required evidence **blocks** rather than defaulting |
| **the factor matrix** | five factor families and their contracts — **families and contracts, not formulas** |
| **`CandidateIntent`** | its required content, and the content it may **never** carry |
| **the decision states** | a closed eight-member vocabulary |
| **candidate consolidation** | one economic opportunity, many evidence paths, module attribution preserved |
| **`StrategySpec`** | a versioned immutable module definition, including its research governance |
| **the lifecycle** | eleven stages, none advanced by code, a backtest or an AI recommendation |
| **immutable versioning** | production versions never mutate; open positions stay pinned to the versions that opened them |
| **Champion / Challenger** | comparison mechanics, and promotion only through a human-read governance packet |
| **the health state machine** | seven states, automatic degradation, non-automatic recovery past a governed suspension |
| **the AI contract** | two bounded roles, and the rule that a deterministic failure cannot be rescued by AI |
| **the deterministic compiler** | thirteen ordered validations, stopping at the first refusal, outputting a status and nothing else |
| **the three-layer handoff** | Brain → portfolio/risk → execution, with no module answering all three question classes |
| **the authority matrix** | what may happen automatically, and what requires a human |
| **security and failure invariants** | and the audit journal each decision must leave behind |

### 2.1 The closed decision-state vocabulary

```text
READY_FOR_RISK_REVIEW     WATCHLIST                REJECTED
BLOCKED_DATA              BLOCKED_EVENT            BLOCKED_AI
BLOCKED_CONTRADICTION     BLOCKED_BORROW
```

**`MAYBE`, `BUY`, `SELL`, `EXECUTE` and `APPROVED_ORDER` are refused by name.** Each reads as an
instruction, and the Brain issues none.

**`READY_FOR_RISK_REVIEW` is not an approval to trade** — it records the absence of a deterministic
objection, and portfolio and risk decide independently.

### 2.2 The `CandidateIntent` exclusion, as a structural property

`CandidateIntent` **may never** carry shares, a dollar amount, a final position size, a final broker
order type, a broker route, a client order ID, a broker order ID, a credential, an account number or
an arbitrary free-form execution instruction.

**The exclusion must be structural, not conventional.** No field of any of those meanings, no
free-text field an instruction could arrive through, and no extension point that admits one — so
that "Brain output cannot be treated as a broker ticket" is a property of the type rather than a
rule a later author could relax. **The technical stop is a reference to an invalidation level, not
an order**; constructing a protective order from it is execution's work under
[ADR-0004](ADR-0004-deterministic-order-identity-idempotency-and-execution-lifecycle.md).

### 2.3 Short alpha is asymmetric

**No generic "Breakdown Short" is authorized, and a short module may not be produced by inverting a
long breakout.** Borrow, fees, recall, squeeze dynamics, SSR, gap asymmetry and an unbounded loss
profile have no long-side mirror. **Bottom-decile momentum alone is not short authorization** —
weak price action is timing information, not an economic reason a short return exists.

`BLOCKED_BORROW` is a first-class state, **borrow may never be inferred from price behaviour**, and
the **live pre-submit borrow recheck belongs to execution and risk**, not to the Brain.

### 2.4 Self-maturing, not self-governing

Restated from ADR-0006 §C and extended with the Brain-specific surfaces, **not weakened**:
automation may monitor, diagnose, research, generate hypotheses, preregister bounded experiments,
run approved-scope studies later, operate shadow challengers, prepare governance packets, reduce or
disable new entries under preapproved safety rules, and fail closed. **It may never** promote a
strategy into order-producing Paper or live operation, replace a production strategy or model,
change production parameters, increase capital, risk, leverage or short exposure, purchase a
licence, add a provider, resume a governed suspension, or bypass the kill switch.

---

## 3. What this decision does not do

**Merging this ADR authorizes architecture, contracts, governance and future implementation
boundaries. It authorizes no implementation and no execution.**

Explicitly, ADR-0026 does **not** authorize:

> Brain runtime implementation · strategy, scanner or factor implementation · AI Research or
> Challenger agent implementation · portfolio or risk engine implementation · order routing or any
> broker action · backtesting of any kind · provider data usage · a provider request · an S3 or AWS
> operation · a Terraform command · a credential retrieval · private-artifact access · a Run A
> retry · Run B · the combined assessment · a P1–P9 execution · a provider selection · a G1 or G2
> decision · Paper expansion beyond the certified Phase-2 scope · micro-live · live trading · any
> capital change · leverage

**A described architecture is not permission to build it** (ADR-0006 §H), and **specification,
implementation, research, deployment and execution are five separate gates** that are never
collapsed into one. Each later gate requires its own explicit written authorization per
`CLAUDE.md` §8.

**No source module is created by this decision.** Nothing is added under `src/`, no placeholder
strategy package is created, and no empty scaffolding is added to make a roadmap look started.

**No gate is closed.** **G1 OPEN · G2 OPEN · G3 CLOSED · G4 OPEN · G5 OPEN · G6 OPEN · G7 OPEN**,
ADR-0005 **PROPOSED**, INC-0002 **OPEN**, Phase 3 **NOT COMPLETE**, CONTROL publication
**DEFERRED**, live trading **HARD-DISABLED**.

**No ADR is amended or superseded.** ADR-0006's taxonomy, boundary and authority split are refined
into checkable contracts, not altered; ADR-0004's execution-identity rules are referenced, not
changed; ADR-0005 remains proposed and this decision does not accept it.

### 3.1 No alpha is claimed

The specification claims **no** economic result. It does not claim that Breakout works, that
Pullback works, that PEAD works, that Deterioration Short works, that AI adds alpha, that residual
momentum is superior, that an options overlay helps, or that any expected return is established.
**Every strategy statement is a hypothesis to be validated**, and the specification's own experiment
matrix is a list of unanswered questions rather than a summary of findings.

---

## 4. Alternatives considered

| Alternative | Why rejected |
|---|---|
| **Specify nothing; write contracts inside the first implementation pull request** | the boundary would be decided by whoever implemented first, inside a diff nobody reviews as architecture. The `CandidateIntent` exclusion in particular is worth more as a reviewed contract than as an implementation detail |
| **Wait for Run B, the combined assessment and G1 before specifying** | the specification takes no dependency on provider data and produces none. Waiting would delay the reviewable artifact without improving it, and would leave the Brain undefined at the moment implementation is first requested |
| **Implement a minimal Brain alongside the specification** | that collapses two gates into one. Implementation is a separate authorization, and it is additionally blocked by qualification that has not completed |
| **Add empty `src/` packages so the roadmap looks started** | scaffolding is not progress, and an empty package invites a later session to fill it without an authorization |
| **Let AI rescue a deterministic block when its evidence is strong** | it inverts the locked principle. AI would then decide eligibility, which is the one thing the boundary exists to prevent. AI may remove a candidate; it may never restore one |
| **Allow a generic inverse-breakout short module** | it treats short as a mirrored long. The asymmetries are structural, not parameters, and pretending otherwise produces a short book with no short alpha |
| **Let `CandidateIntent` carry a suggested size "for information only"** | a suggested size is a size. A downstream layer, a log reader or a later author eventually treats it as one, and the structural guarantee is gone |

---

## 5. Consequences

**Good.**

- The Brain's boundary becomes a reviewed contract instead of an intention, so "AI cannot size or
  route" is checkable before any code exists.
- A later implementation slice has an unambiguous target and can be reviewed against it.
- Strategy governance — lifecycle, versioning, promotion, health — is decided while nothing is at
  stake, rather than under pressure from a degrading live strategy.
- The short-side asymmetry is recorded as architecture, so a short book cannot arrive as a mirrored
  long one.
- Documentation guards now assert these invariants, so a later edit that quietly relaxes one fails
  the audit instead of merging.

**Costs, accepted.**

- A specification with no implementation can drift from what is eventually built. Mitigated by the
  documentation audit and the governance tests, which fail when the recorded invariants change.
- The document is long. That is the cost of specifying a boundary precisely enough that it cannot be
  reinterpreted, and the alternative is a boundary decided inside a later diff.
- Some contracts will need revision once qualified data exists. A revision is a new reviewed ADR,
  which is the intended mechanism rather than a defect.

**Neutral.**

- No source code, dependency or runtime configuration change. No network call, no provider contact,
  no AWS or Terraform operation, no broker action.

---

## 6. Compliance

| Check | State |
|---|---|
| Source code changed | **none** |
| Dependencies changed | **none** |
| Runtime configuration changed | **none** |
| Broker activity | **none** |
| Provider activity | **none** |
| AWS / STS / SSO / IAM / Secrets Manager / S3 activity | **none** |
| Terraform commands | **none** |
| Private artifacts read | **none** |
| Blueprint PDFs opened | **none** |
| Backtests run | **none** |
| Run A retry / Run B / combined assessment | **not run, not authorized** |
| P1–P9 | **UNEVALUATED** |
| Provider selected | **NONE** |
| G1 / G2 | **OPEN / OPEN** |
| Phase 3 | **NOT COMPLETE** |
| CONTROL publication | **DEFERRED** |
| `LIVE_TRADING_HARD_DISABLED` | **True** |
| Repository visibility | **PUBLIC** (development); must return PRIVATE before micro-live or real money |
| INC-0002 | **OPEN** |
