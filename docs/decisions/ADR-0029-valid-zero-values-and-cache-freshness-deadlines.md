# ADR-0029 — A zero is a value, and a cache spends a freshness budget it never refills

**Status: PROPOSED — NOT IN FORCE. No authority until PR #73, the pull request introducing this
ADR, is independently reviewed and merged.**

While PR #73 is open, ADR-0029 is proposed and carries no authority, and so are the two corrections
it makes to `read-model-contracts.md` in the same pull request. That is a statement about the
present, it will remain true of these days after any later merge, and it is not to be rewritten as
though this decision had authority before it was accepted. On merge, this ADR becomes **ACCEPTED /
IN FORCE** as **two corrected contract rules** — and nothing else.

**The acceptance event is exact:** the independent review and merge of **PR #73** into `main`. No
merge SHA and no merge timestamp is predicted here; those are repository state, recorded after the
fact if they are recorded at all.

**Date:** 2026-09-05
**Supersedes:** nothing
**Superseded by:** —
**Amends:** two clauses of
[`read-model-contracts.md`](../cockpit/read-model-contracts.md), listed exactly in §3. **It does not
amend, supersede or edit [ADR-0027](ADR-0027-cockpit-and-feedback-architecture-and-governance.md) or
[ADR-0028](ADR-0028-cockpit-contract-completion-and-boundary-corrections.md) themselves.**
**Relates to:** [ADR-0026](ADR-0026-strategy-brain-architecture-and-governance.md),
[ADR-0027](ADR-0027-cockpit-and-feedback-architecture-and-governance.md),
[ADR-0028](ADR-0028-cockpit-contract-completion-and-boundary-corrections.md)

**Nothing was run to produce this decision.** No AWS, STS, SSO, IAM, Secrets Manager or S3 call; no
Terraform command of any kind; no Terraform state, backend configuration, `.tfvars` or `.terraform/`
read; no `.runtime/` inspection; no provider request; no credential access; no Run A retry, Run B or
combined assessment; no P1–P9 execution; no backtest; and no broker, LEAN or IBKR activity. **No
Blueprint PDF was opened or edited.** No dependency was installed, no package manifest was changed,
and no application was scaffolded. This decision is authored from tracked repository authority alone.

**No alpha is claimed anywhere in this decision.**

---

## 1. Context

**ADR-0028 is ACCEPTED / IN FORCE.** It was accepted by the independent review and merge of **PR #72**
into `main` — merged **2026-09-05T18:03:14Z**, merge commit
**`fb6789da74ff28c3a2aafae88298d63f3ba5f721`**, final reviewed pull-request head
**`0f38141615f9dabb91dce6c17671b648045036c2`**. **Its conditional acceptance event has occurred**, and
the conditional status text ADR-0028 was written with is preserved as the record of the days before
that merge rather than rewritten. **This decision does not revert, reopen or restate ADR-0028 as
proposed**, and it corrects neither its four original corrections nor the four found by its review.

**Two rules ADR-0028 introduced are wrong, and each lets a conforming implementation reach a false
conclusion.** They are narrow, they are not editorial, and they are corrected here rather than left
to an implementation cycle to discover.

### 1.1 A zero was declared correct in exactly one availability state

§4.1.1's validity matrix named `EMPTY_VERIFIED` as **the only state in which a zero is a correct
answer**. **That is false of every measurement that legitimately evaluates to zero.** A day with no
realized profit, a position with no drawdown, a fill at the reference price, a flat net exposure and
a strategy that won none of ten trades are all **measurements**, produced by a producer that ran, and
each of them is a zero that `AVAILABLE` must be able to carry.

**The rule confused the number with the population.** `EMPTY_VERIFIED` describes a completed query
whose **defined result population is empty**; the count of an empty population is indeed zero, and
**the converse does not follow**. Zero winners among ten closed trades is a measured zero over a
**non-empty** population, and a consumer obeying the retired rule had two bad options: relabel a real
finding `EMPTY_VERIFIED`, which asserts there were no trades, or withhold it as though nobody had
answered. **A strategy that won nothing is a result a screen must show.**

**The test that guarded it could not catch it.** `test_empty_verified_is_the_only_state_in_which_a_zero_is_correct`
asserted which states are value-bearing — that `EMPTY_VERIFIED` carries a value and that
`NOT_YET_AVAILABLE` and `NOT_IMPLEMENTED` do not. **Every one of those assertions stays true under the
corrected rule**, so the test agreed with the defect and with its correction equally, and it never
examined a zero at all.

### 1.2 A cache lifetime was bounded by the whole freshness window

§3.1 and §7 bounded a cache entry's life at **the strictest `contract_max_age` it carries**. **That
returns age the fact had already spent.** A source fact observed 290 seconds before an entry is built,
under a 300-second contract, has **10 seconds of eligibility left** — and the retired rule granted the
entry a further 300, so a consumer could read a 590-second-old fact as `AVAILABLE` against a
300-second contract.

**This contradicts a rule the same document already states.** §3.1 establishes that `source_age` is
measured from `source_effective_time`, and that **a rebuild resets `build_age` and never
`source_age`**. A cache that restarts the clock is that same defect at a different layer: it makes
the age of the *entry* stand in for the age of the *facts*.

**A composite made it worse.** With several required inputs on different contracts, the entry's life
was governed by the strictest **contract**, which is not the earliest **deadline**. An input 40
seconds old on a 60-second contract expires in 20 seconds; an input 290 seconds old on a 600-second
contract expires in 310. The strictest contract is the first; the binding deadline is also the first —
but change the second contract to 300 seconds and the binding deadline moves, while the strictest
contract does not. **Only an absolute per-input deadline gets this right in every case.**

---

## 2. Decision

### 2.1 A zero is a measurement, and never an availability state

**`AVAILABLE` with `NONE` may carry a numeric zero**, and **the numeric value alone never determines
availability**. A zero realized P/L, a zero drawdown, a zero slippage, a zero net exposure and a
measured count of zero are **results**.

**`EMPTY_VERIFIED` is a statement about the population**: the query **ran**, with evidence that it ran,
and the **defined result population is empty**. **An empty population's count is zero; not every zero
count implies an empty population**, and the two are different answers to different questions.

**A qualification is not removed by a zero.** A zero carried by `STALE` is still stale and a zero
carried by `PARTIAL` is still partial. **Absence stays absent**: `NOT_YET_AVAILABLE`,
`NOT_IMPLEMENTED`, `NOT_AUTHORIZED`, `UNEVALUATED`, `INSUFFICIENT_OBSERVATIONS` and `ERROR` carry no
value, and **a producer that cannot answer never substitutes zero for the answer**. **Undefined
arithmetic is not a zero result**: `DENOMINATOR_ZERO` remains a statement about the denominator, the
state remains `NOT_APPLICABLE` and the value remains absent, while **a zero numerator and a quotient
that legitimately evaluates to zero are values**.

**No availability state is added, no reason code is added, and no missing-data safeguard is
relaxed.** The matrix of §4.1.1 is unchanged in membership and in permitted pairings.

### 2.2 A freshness deadline is absolute, and a cache spends it

**Each required input carries its own absolute deadline, and a composite expires at the earliest.**

```text
input_deadline        = source_effective_time + contract_max_age   -- ABSOLUTE, and per input
fresh_until           = minimum(input_deadline over every REQUIRED input)
remaining_freshness   = max(0, fresh_until - cache_or_serve_time)  -- what is LEFT, in seconds
```

**The clamp at zero bounds the remaining budget and nothing else.** It never hides clock skew and
never clamps an invalid, negative or unknown source age — those refuse under §3.1 as they already did.

**The comparison is stated once**, so two layers cannot disagree: **`serve_time < fresh_until`** permits
`AVAILABLE` if every other rule already permits it, and **`serve_time >= fresh_until`** means the entry
is expired and must be revalidated or downgraded to `STALE`.

**The oldest input is reported; the earliest deadline binds.** §3.1's rule that a composite reports
`source_age` against the **oldest** required input is unchanged — it answers *how old are the facts*.
A deadline answers *how long does this answer stay fresh*, and with unequal contracts the two name
**different inputs**. Neither rule replaces the other.

**Retaining content is not claiming it is fresh.** An expired entry may be kept and served, **explicitly
`STALE` with `UPSTREAM_INPUT_STALE` and never `AVAILABLE`**. **A refetch, a rebuild or a re-cache over
the same old facts renews nothing**, because `source_effective_time` is unchanged. **A configured TTL
may shorten and never extend**; an origin, intermediate and browser cache each expire at the **same
absolute `fresh_until`**, and elapsed time in transit spends the same budget. **Unknown timing
establishes no deadline** — no default TTL is invented — and **a remaining budget is a ceiling on
freshness, never a grant of it**, so an input already `STALE`, `PARTIAL`, missing or in `ERROR` stays
in that state. **Optional inputs answer for themselves**, do not set `fresh_until`, and never conceal
a required input's failure.

---

## 3. Exactly what is amended

**No ADR document is edited by this decision.** ADR-0027 and ADR-0028 stand, text, status lines and
historical records included. What this decision amends is **two clauses of one specification**.

| Document | Clauses |
|---|---|
| [`read-model-contracts.md`](../cockpit/read-model-contracts.md) | §3.1 freshness, at the cached-response rule, with **new §3.1.1** · §4.1.1 the validity matrix, at the `EMPTY_VERIFIED` row, with **new §4.1.2** · §7 caching, at the *freshness is data, not policy* row |

**No other clause of that document changes**, and **no other document's clauses change** — not
`cockpit-v1-specification.md`, not `feedback-self-maturation-specification.md`, not
`ui-ux-specification.md`, not `traceability-matrix.md` and not `COCKPIT_FEEDBACK_EXTENSION.md`.

---

## 4. What is preserved, unchanged

```text
all 36 product areas stay in V1 scope        the C1-C10 delivery sequence is unchanged
the AvailabilityState vocabulary is unchanged -- no member added, renamed or removed
the FieldReasonCode vocabulary is unchanged -- no member added, renamed or removed
the 4.1.1 validity matrix is unchanged in membership and in permitted pairings
NOT_APPLICABLE still has exactly two routes, and a missing input is neither
source_age, projection_lag and build_age are unchanged, and a rebuild still refreshes nothing
the composite still reports the OLDEST required input and the WORST required state
missing, skewed and future timestamps still refuse rather than resolve
the Brain ends at CandidateIntent            sizing and execution stay downstream
V1 stays observational and READ-ONLY is still defined by absence
the licensed and private data boundaries are unchanged, and so is the immutable audit
no risk limit, capital value, leverage setting, sizing rule or stop policy changes
no Blueprint PDF is opened or edited         no source module is created
no dependency is installed                   no application is scaffolded
```

---

## 5. Alternatives considered

**Leave the zero rule and let producers work around it.** Rejected: the two available workarounds are
to relabel a measured zero `EMPTY_VERIFIED`, which asserts an empty population that does not exist, or
to withhold it, which reports that nobody answered when somebody did. **Both are false reports**, and a
contract that forces one is the defect.

**Add a state meaning "a legitimate zero".** Rejected: availability answers *is there an answer*, and a
zero is an answer. A separate state would put the same question on two axes, which is exactly the
crossed-axes defect ADR-0028 §2.5.1 closed.

**Bound the cache by the strictest contract and shorten it by convention.** Rejected: a convention that
is not in the contract is not checkable, and the arithmetic is only correct when the deadline is
absolute. **A per-input absolute deadline is the same rule at every layer**, which is what lets an
origin, an intermediate and a browser cache agree without coordinating.

**Recompute freshness at serve time from a stored `source_age`.** Rejected: a stored age is a number
measured at another instant, so recomputing from it re-derives the same error. **The stored quantity
must be the instant, not the age.**

---

## 6. Consequences

**A screen can show a measured zero as a finding**, and a reviewer can tell a measured zero from an
empty population without reading the producer. **A cached response cannot outlive its source's
eligibility**, at any layer, and an expired entry degrades to `STALE` rather than rendering green over
dead data.

**The corrections are executed, not only asserted.** `tests/unit/test_cockpit_contract_semantics.py`
parses the decided zero cases and the three deadline formulas **out of the specification** and drives
fixtures through them, so restoring either retired rule fails the suite rather than passing against a
private copy. **Both retired rules are additionally guarded by name.**

**Nothing is implemented by this decision**, and no producer, cache, projection or endpoint exists to
obey it.

---

## 7. What acceptance would and would not mean

**On independent review and merge, this ADR accepts two corrected contract rules — and nothing else.**
**Acceptance authorizes no implementation and no execution.**

| | |
|---|---|
| The two corrected contract rules | **ACCEPTED EFFECTIVE ON MERGE OF PR #73** |
| Cockpit application implementation | **NOT STARTED / NOT AUTHORIZED** |
| Read-model, projection, metric-engine, cache and API implementation | **NOT STARTED / NOT AUTHORIZED** |
| Feedback and learning-engine implementation | **NOT STARTED / NOT AUTHORIZED** |
| Brain runtime implementation | **NOT STARTED / NOT AUTHORIZED** |
| Portfolio, risk, strategy, factor, scanner and AI-agent implementation | **NOT STARTED / NOT AUTHORIZED** |
| Database, migration, scheduler, container and deployment | **NOT STARTED / NOT AUTHORIZED** |
| Backtesting | **NOT STARTED** |
| Run A retry | **NOT AUTHORIZED / NOT RUN** |
| Run B | **NOT RUN / NOT AUTHORIZED** — earliest approved target 2026-09-12, at least eight calendar days after Run A |
| Combined assessment | **NOT RUN / NOT AUTHORIZED** |
| P1–P9 | **UNEVALUATED** |
| Data correctness and quality | **NOT ESTABLISHED** |
| G1 / G2 | **OPEN / OPEN** |
| Provider selected | **NONE** |
| Phase 3 | **NOT COMPLETE** |
| CONTROL publication | **DEFERRED** |
| `LIVE_TRADING_HARD_DISABLED` | **True** |
| Live trading | **HARD-DISABLED** |

**No ADR is amended or superseded.** ADR-0028 is **ACCEPTED / IN FORCE** through the merge of PR #72,
ADR-0027 through the merge of PR #71 and ADR-0026 through the merge of PR #70, and this decision
changes nothing in any of them — it corrects two clauses of one specification ADR-0027 adopted and
ADR-0028 amended. ADR-0005 remains **PROPOSED**. ADR-0006's authority split is applied, not altered.

**Passing the 2026-09-12 date gate is not execution authorization.** Run B still requires its own fresh
prompt and its own written authorization, and so does the combined assessment. **The at least eight
calendar day Run A to Run B separation is unchanged.**

**Specification, implementation, research, deployment and execution are five separate gates**, and they
are never collapsed into one. This decision stays inside the first.

---

## 8. Governance status at the time of this decision

```text
G1 OPEN · G2 OPEN · G3 CLOSED · G4 OPEN · G5 OPEN · G6 OPEN · G7 OPEN
ADR-0005 PROPOSED · ADR-0026 ACCEPTED / IN FORCE · ADR-0027 ACCEPTED / IN FORCE
ADR-0028 ACCEPTED / IN FORCE · INC-0002 OPEN
Phase 3 NOT COMPLETE · CONTROL publication DEFERRED · live trading HARD-DISABLED
Run A COMPLETED ONCE, 2026-09-04 · Run A retry NOT AUTHORIZED
Run B NOT RUN / NOT AUTHORIZED · earliest approved target 2026-09-12
combined assessment NOT RUN / NOT AUTHORIZED · P1–P9 UNEVALUATED
provider selected NONE · backtesting NOT STARTED
```

**Each gate is read on its own.** G3 is closed for the Sharadar personal-use licence and nothing else
([ADR-0008](ADR-0008-sharadar-personal-use-license-and-private-qualification.md)); the other six are
open for their own reasons. **No blanket statement about all seven is correct.**
