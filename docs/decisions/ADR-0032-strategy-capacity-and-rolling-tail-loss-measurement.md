# ADR-0032 — Strategy capacity and rolling tail-loss measurement contracts

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0032 is proposed and carries no authority,
and so are the deltas it makes to the Cockpit specifications in the same pull request. That is a
statement about the present, it will remain true of these days after any later merge, and it is not
to be rewritten as though this decision had authority before it was accepted. On merge, this ADR
becomes **ACCEPTED / IN FORCE** as **measurement contracts, area ownership and governance** — and
nothing else.

**The acceptance event is exact:** the independent review and merge, into `main`, of the pull
request introducing this ADR. No merge SHA and no merge timestamp is predicted here; those are
repository state, recorded after the fact if they are recorded at all.

**Date:** 2026-09-09
**Supersedes:** nothing
**Superseded by:** —
**Amends:** [`docs/cockpit/read-model-contracts.md`](../cockpit/read-model-contracts.md) at §12.3
with two new metric rows, the new §12.3.2 and §12.3.3, a §12.6 note, and the §4.5
`StrategyPerformance` and `StrategyHealth` payload notes; and
[`docs/cockpit/traceability-matrix.md`](../cockpit/traceability-matrix.md) at the acceptance
criteria of **Area 4** and **Area 5** only. **It amends no other section of either document**, and
**it does not amend, supersede or edit ADR-0026, ADR-0027, ADR-0028, ADR-0029, ADR-0030 or
ADR-0031**, each of which remains as it stands.
**Relates to:** [ADR-0026](ADR-0026-strategy-brain-architecture-and-governance.md),
[ADR-0027](ADR-0027-cockpit-and-feedback-architecture-and-governance.md),
[ADR-0029](ADR-0029-valid-zero-values-and-cache-freshness-deadlines.md)

**Nothing was run to produce this decision.** No AWS, STS, SSO, IAM, Secrets Manager or S3 call; no
Terraform command of any kind; no Terraform state, backend configuration, `.tfvars` or `.terraform/`
read; no `.runtime/` inspection; no provider request; no credential access; no Run A retry, Run B or
combined assessment; no P1–P9 execution; no backtest; no model calibration; and no broker, LEAN or
IBKR activity. **No Blueprint PDF was opened or edited.** No dependency was installed, no package
manifest was changed, and no runtime behaviour was implemented. This decision is authored from
tracked repository authority alone.

**No alpha is claimed anywhere in this decision, and no parameter in it is a trading rule.**

---

## 1. Context — two named requirements with no definition behind them

**Two accepted Cockpit requirements name a quantity that nothing in tracked authority defines.**
That is the whole problem, and it is a contract gap rather than an implementation backlog: an
implementation cycle asked to deliver either one would have to invent the definition on a screen,
which is precisely what §12.6 exists to prevent.

```text
1  cockpit-v1-specification.md Area 5 -- Strategy Health -- Presents
       "With rolling expectancy, drawdown and TAIL LOSSES"
2  cockpit-v1-specification.md Area 4 -- Strategy Performance -- Presents
       "... turnover, slippage, CAPACITY, MFE, MAE and capture ratio"
3  read-model-contracts.md 12.3 carries NO ROW for either quantity -- no formula,
       no unit, no denominator, no basis, no minimum-observation rule and no
       stated unavailable outcome
4  12.1 requires every metric to declare each of those, and 12.2 requires a stable
       metric_id under a stated metric_definition_version
```

**A registered unit is not a definition, and the difference is the gap.**
`apps/cockpit/src/contracts/values.ts` registers `strategy.tail_loss` with unit `R_MULTIPLE` and
`strategy.capacity` with unit `USD`. A unit fixes how a number is rendered. It fixes **nothing**
about what was measured, over which population, across which window, by which statistic, or what is
returned when the answer cannot be computed. Two implementations can satisfy both registrations and
report different numbers under one `metric_id`, which is the drift §12.2 exists to prevent.

**The merged C5 completion follow-up named both gaps precisely and closed neither**, which was the
correct disposition for an implementation cycle. It records that the metric dictionary carries **no
formula, denominator, participation assumption or minimum-observation rule** for capacity, and that
a tail-loss measure has no definition anywhere. This ADR answers both questions, and it answers
**only** those two.

### 1.1 Ownership, verified rather than assumed

| Requirement | Owning area | Read-model owner | Cycle | Accepted clause |
|---|---|---|---|---|
| **rolling tail losses** | **Area 5 — Strategy Health** | `StrategyHealth` | **C7** | Area 5 *Presents*; traceability Matrix A row 5 and Matrix B row 5 |
| **strategy capacity** | **Area 4 — Strategy Performance** | `StrategyPerformance` | **C5** | Area 4 *Presents*; traceability Matrix A row 4 and Matrix B row 4 |

**Rolling tail losses are named exactly once in the specification, and it is in Area 5.** They are
therefore a **C7** surface, and this ADR **does not move that requirement into C5**. That the C5
completion follow-up reported the gap does not transfer ownership: reporting a gap and owning it are
two different things, and the traceability matrix is what assigns an area to a cycle.

**Capacity is an Area 4 requirement and stays one.** It is additionally carried on
`ResearchRun.payload.capacity` (§4.5), which is an **Area 14** consumer of the same `metric_id` —
so one definition has to serve both, and this ADR defines it once rather than twice.

### 1.2 What is not the gap

**A missing table row alone would not prove a conflict.** The gap is established positively: §12.1
imposes eight requirements on every metric, §12.3 states that its rows are where those requirements
are met, and neither quantity has a row. **Nothing else in tracked authority supplies them** — the
Brain specification names tail losses and capacity as health inputs without defining either, the
feedback specification names capacity analysis as a research output without defining it, and §12.6
records that where no accepted definition exists a presentation definition must be **proposed and
labelled**. This ADR is that proposal, raised to an accepted contract rather than a screen comment.

---

## 2. Decision

**Two metric definitions are added to §12.3, each with a worked subsection.** One is computable from
records this repository's contracts already define. The other is not computable from any record and
is therefore specified as a **qualified-model interface with an admission gate**, so that a capacity
value can never appear without the evidence that makes it meaningful.

**Every parameter this ADR chooses is labelled a PROPOSED MEASUREMENT DECISION.** A proposed
measurement decision is not an existing requirement, is not a production qualification, and is
**never** a trading threshold, a promotion criterion, a health-state transition rule, a risk limit
or a capital authorization.

---

### D1 — `strategy.tail_loss`, the rolling tail loss

**D1.1 Subject.** **One exact strategy version.** Not a module, not an alpha family, not the
portfolio. `StrategyHealth` is keyed by `strategy_version` and every result in this repository is
attributed to the exact version that produced it; a tail loss aggregated across versions would
attribute one version's tail to another.

**D1.2 Measured population.** **Closed trades of that exact strategy version that carry a recorded
`risk.initial_planned`** — the population `PerformanceSummary` already declares as
`CLOSED_TRADES_OF_THIS_EXACT_VERSION`, narrowed by the eligibility `r_multiple` already requires.
**One trade contributes exactly one observation**, at its close.

**D1.3 The population contains every eligible observation, and not only losses.** This is a decision
and not an oversight. A losses-only population makes the statistic move when the **win rate** moves:
a version that stopped losing would shrink its own denominator to the few remaining losses and
report a *worse* tail on *better* behaviour. It also leaves the metric undefined for a version with
no losing trade, when the correct answer there is a measured number. **The tail is selected by
ordering, never by filtering on sign.**

**D1.4 Units and sign.** **`R_MULTIPLE`**, as already registered. Each observation is that trade's
`r_multiple` under §12.3, and **§12.1's sign convention is carried unchanged: profit positive, loss
negative, for both long and short.** A tail loss is therefore **a negative number when the worst
outcomes lost money, and a more severe tail loss is more negative.** No magnitude convention, no
sign flip and no absolute value is introduced.

**D1.5 A positive tail loss is a measured result.** When the worst observations in the window were
profitable, the statistic is positive, and it is `AVAILABLE` with `NONE`. It is not an error, not a
substitution and not a reason to withhold the value. §4.1.2 already holds that a zero is a
measurement; the same reasoning holds for a positive tail.

**D1.6 The statistic — a conditional tail expectation over order statistics.**

```text
n              the number of eligible observations in the window
q              the declared tail fraction
k              ceil(q * n), the tail observation count -- an INTEGER COUNT OF
               ORDER STATISTICS, so NO QUANTILE INTERPOLATION RULE IS NEEDED
r(1) <= r(2) <= ... <= r(n)      the eligible r_multiple values, ascending

strategy.tail_loss  =  ( r(1) + r(2) + ... + r(k) ) / k
```

**The mean of the `k` most adverse eligible observations.** `k` is an integer by construction and
`k >= 1` whenever the minimum observation count is met, so **`strategy.tail_loss` has no
zero-denominator route of its own** and `DENOMINATOR_ZERO` is unreachable for it.

**D1.7 It is a mean of ratios, and never a ratio of sums.** Each observation carries **its own**
denominator — that trade's retained `risk.initial_planned`, summed across stages under §12.4's
adds-and-pyramids rule, fixed at entry and never moved by a trailing stop. **The statistic is
therefore not total tail dollars divided by total tail risk dollars**, which would silently weight
the tail by position size and report a different quantity under the same name.

**D1.8 Window membership, ordering, ties and the point-in-time cutoff.**

| | |
|---|---|
| **the window is a closed-trade count window** | the trailing **N** eligible observations. **Never a calendar window** — a version that traded twice in a quarter would otherwise produce a two-observation tail under a quarterly heading |
| **the observation unit is stated, never assumed** | closed trades, not series periods, and the two never substitute. **§12.3 declares no rolling expectancy row**, so this rule is stated here on its own account rather than inherited from one |
| **an observation enters at its close instant** | not at entry. A trade's outcome is not known until it closes, and admitting it earlier would place information in a window before it existed |
| **recency ordering** | by close instant ascending; ties broken by trade identifier ascending, so window membership is deterministic |
| **severity ordering** | by `r_multiple` ascending, most adverse first |
| **ties in severity need no tie-break for the value** | tied observations carry the same `r_multiple`, so the mean over any `k`-subset of a tie is identical. A deterministic order is still declared, for evidence listing |
| **the point-in-time cutoff** | at an evaluation point `P`, only observations whose close instant is at or before `P` are eligible |
| **future observations are excluded, in the strong form** | appending a later observation changes no earlier value, and **replacing every observation after `P` changes nothing at or before `P`**. The weaker no-look-ahead phrasing is not the rule; this is |

**D1.9 Open trades, partial exits and adds.**

| | |
|---|---|
| **open trades** | **excluded.** An open trade's outcome can still move, so including it would let a tail loss improve with no new information |
| **partial exits** | §12.4 governs unchanged: **a partial exit reduces a trade; it does not close it and does not create a second one.** A partially exited trade is still open and contributes **no** observation |
| **adds and pyramids** | one trade, one observation. The denominator is the **sum of the retained per-stage initial planned risks**, and no stage becomes an observation of its own |
| **entry facts stay separate from adds** | this ADR reads the retained records and alters none of them. No entry fact, add-stage fact, risk denominator or strategy version is changed |

**D1.10 Minimum observations, and insufficiency versus a measured zero.**

| Situation | `availability` | `reason` |
|---|---|---|
| a full window of eligible observations, statistic computed | `AVAILABLE` | `NONE` |
| a computed statistic of exactly `0.00` R over a full window | `AVAILABLE` | `NONE` — **a measured zero, and never an absence** |
| fewer eligible observations than the declared minimum | `INSUFFICIENT_OBSERVATIONS` | `BELOW_MINIMUM_OBSERVATIONS`, **value absent** |
| **zero** eligible observations | `INSUFFICIENT_OBSERVATIONS` | `BELOW_MINIMUM_OBSERVATIONS` |
| a closed trade in the walk-back excluded for a missing or zero `risk.initial_planned`, **with the minimum met** | `PARTIAL` | `UPSTREAM_INPUT_MISSING`, **naming how many were excluded** |
| fewer eligible observations than the minimum **and** closed trades also excluded | `INSUFFICIENT_OBSERVATIONS` | `BELOW_MINIMUM_OBSERVATIONS`, **value absent** — the exclusion count is still disclosed |
| no producer exists | `NOT_IMPLEMENTED` | `PRODUCER_NOT_IMPLEMENTED` |

**An empty population is `INSUFFICIENT_OBSERVATIONS` and not `EMPTY_VERIFIED`.** §4.1.2 reserves
`EMPTY_VERIFIED` for the **count of a defined population**, and this metric is a statistic rather
than a count: §4.1.1 gives `INSUFFICIENT_OBSERVATIONS` no value at all, which is the correct answer
when there is nothing to average. **One situation gets one state.**

**The exclusion rule follows the accepted `slippage.aggregate` precedent** — excluded members are
counted and the result is `PARTIAL` naming how many — rather than inventing a second convention for
a silently reduced population.

**Sufficiency is decided before exclusion, and the two answers are never both returned.** A walk-back
can satisfy neither condition, one of them, or both at once, so the rule is stated rather than left
to a reader: **the eligible count decides the metric value first.** Below the minimum the value is
`INSUFFICIENT_OBSERVATIONS` with `BELOW_MINIMUM_OBSERVATIONS` and **carries no value at all**,
*whether or not* closed trades were also excluded during the walk-back. **`PARTIAL` is reachable only
when the minimum is met**, because §4.1.1 requires a `PARTIAL` value to be **present** and an
insufficient population has no value to qualify. **This is one metric's own rule, read off the
validity matrix, and it is not a precedence policy over availability states generally.**

**The exclusion count is disclosed either way, and it is not the metric value.** How many closed
trades the walk-back excluded is a **population disclosure carried beside the metric** — the same
count the `PARTIAL` row names — and it is stated in the insufficient case too, so a reader is never
told a window was merely short when part of it was also unusable. **Disclosing it never converts an
absent value into a valued `PARTIAL`**, and no valued result is ever manufactured from a population
too small to produce one.

**D1.11 What it is not.**

| | |
|---|---|
| **not `drawdown.max` or `drawdown.rolling_max`** | drawdown is **path-dependent** over an equity series measured against a running peak, compounds across overlapping trades and includes open marks. A tail loss is **cross-sectional over discrete closed outcomes**: no path, no peak, no compounding. A version can carry a mild tail and a severe drawdown, or the reverse |
| **not `expectancy.r`** | expectancy is the mean over the **whole** population and answers *what does an average trade return*. The tail loss is the mean over the **worst `k`** and answers *when it goes wrong, how wrong* |
| **not the worst single observation** | the minimum `r_multiple` is one order statistic and moves entirely with one outlier. **The two are different definitions, and their values can still coincide**: when the `k` most adverse observations are all equal — three tied worst trades under the proposed parameters — the mean of the tail **is** the minimum, and `k` being three prevents nothing. **Coincidence of two values is not identity of two definitions**, and the two diverge as soon as the tail is not flat |
| **not a health-state rule** | Area 5's seven health states and every transition rule come from ADR-0026 §13 and are **unchanged**. Displaying a tail loss causes no transition, and this ADR creates no threshold at which one occurs |

**D1.12 PROPOSED MEASUREMENT DECISIONS.** Each is a choice this ADR makes, offered for review:

| Parameter | Proposed value | Why this, and what it is not |
|---|---|---|
| **statistic** | conditional tail expectation over `k` order statistics | no interpolation convention, deterministic, averages `k` observations rather than resting on one |
| **tail fraction `q`** | **0.10** | a decile is a conventional tail granularity that leaves `k` above one at the proposed window. **Not** a risk limit and not a loss threshold |
| **window `N`** | **30 eligible closed trades** | **reuses §12.3's own declared minimum for `expectancy.currency`** rather than inventing a number. **It is a reused count and not a shared window** — §12.3 declares a **minimum** for the expectancy rows and **no rolling window for either**, so no shared-window claim is made. What *is* shared is the eligibility rule: `expectancy.r` is refused for any trade lacking `risk.initial_planned`, and this population is narrowed the same way |
| **minimum observations** | **30** | the same reused value. A window shorter than the metric's minimum would report `INSUFFICIENT_OBSERVATIONS` at every point by construction, which is not a window |
| **derived `k`** | `ceil(0.10 * 30)`, which is **3** | derived, not chosen separately |

**Reusing a minimum does not make the estimate statistically adequate, and no such claim is made
here.** Thirty is the count §12.3 already declares sufficient for a **mean over a whole population**;
this statistic averages **three**, so its support is far thinner than the window size suggests.
**One observation is a third of the estimate** — replacing a single tail member moves the value by a
third of that member's change — and a tail one observation away from being flat can move sharply on
one trade. **The estimate is descriptive of the window it measured and nothing more**: it carries
**no predictive reliability**, **no production qualification** and **no threshold at which anything
happens**. Whether three observations suffice for whatever a later cycle wants to do with the number
is a question that cycle must answer with evidence, and this contract answers it nowhere.

**None of the five is an existing requirement, a production qualification, an alpha claim or a
trading rule**, and lowering or raising any of them later is an ADR amendment rather than a
configuration change.

---

### D2 — `strategy.capacity`, the strategy capacity estimate

**D2.1 What the estimate means.** **The greatest strategy capital, in USD, that this exact strategy
version could have deployed over the evaluated window while keeping its modelled execution cost
within a declared tolerance of the execution cost its own recorded fills achieved.**

**It is measured against this version's own realized execution, which is what makes it narrower
than its name.** The admissible ceiling is `observed_execution_cost + cost_tolerance`, so a version
whose own fills executed **badly** carries a **higher** ceiling and reports a **larger** capacity
than an otherwise identical version that executed well. **Poor observed execution mechanically
increases the reported number**, and that is a property of the chosen definition rather than a defect
in an implementation of it.

**So the quantity is named for what it is.** It is a **cost-degradation-tolerance capacity, relative
to the version's own observed execution** — *how much more capital this version could have pushed
before its modelled execution cost degraded past its own realized baseline by more than the declared
tolerance*. It is therefore **not comparable across versions whose execution quality differs**, **not
a profitability capacity**, **not the capital at which the strategy stops making money**, **not a
liquidity ceiling** and **not a risk or allocation limit**. **Wherever the value is displayed it
carries that limitation**, because the word *capacity* on its own invites every one of the readings
it is not.

**D2.2 Subject, unit and horizon.** Subject: **one exact strategy version**, as Area 4 is keyed.
Unit: **`USD`**, as already registered — **a level, not a ratio**, so it has no denominator and
states `n/a` for one. Horizon: **the evaluated window of the `PerformanceSummary` it sits beside**,
on that summary's named calendar, with every input aligned to **exactly** those boundaries under
§12.4's benchmark-alignment precedent.

**D2.3 Its relationship to capital allocation is that it has none.** Capacity is an **observation
about a strategy**, never an instruction about capital. It is **not** an allocation, not an
authorization, not a permitted position size and not a scaling permission. Allocation remains the
governed research values of `CLAUDE.md` §6 and the risk engine; capital scaling remains a human
governance decision under §4.20 and ADR-0026.

**D2.4 Why four quantities that are not capacity are not substituted for it.**

| Quantity | Why it is a different question |
|---|---|
| **strategy capital — USD 80,000** | a **governed input**, a decision rather than a measurement. Substituting it makes capacity a restatement of a policy constant that would never move when the strategy's liquidity profile moved |
| **buying power** | a **broker** quantity about what an account may currently transact. It says nothing about what the market would absorb, and §6 holds that broker-reported figures never participate in sizing at all |
| **gross exposure** | a **realized snapshot of what was deployed**. It can never exceed what was deployed, so it could never reveal that a version had room, and could never reveal that it was over capacity |
| **an allocation or position limit** | a **policy ceiling** — the answer to *what are we permitted to do*, not *what would the market absorb* |

**Each of the four is already displayed elsewhere under its own name**, so substituting one here
would render one number twice under two meanings. **A capacity field is never filled from any of
them**, and never filled with zero.

**D2.5 It is not computable from recorded facts alone, and this ADR says so rather than pretending
otherwise.** No ledger, no fill record and no risk record contains what the market would have
absorbed. **Capacity is therefore defined as a qualified-model interface with an admission gate**,
and **no capacity value is admissible until every clause of §D2.6 through §D2.9 holds.**

**D2.6 The admissible rule.**

```text
C*  =  the greatest deployable strategy capital C on the model's declared search grid
       for which

           modelled_execution_cost(C)  -  observed_execution_cost  <=  cost_tolerance

       evaluated over this exact strategy version's recorded trade population,
       over the evaluated window, under the declared participation limit,
       execution horizon and market-impact function
```

**The model must declare `modelled_execution_cost` monotone non-decreasing in `C`, or declare the
search rule that resolves a non-monotone cost function.** Without one of the two, *the greatest `C`*
is ambiguous, and an ambiguous maximum is not a definition.

**The search domain is declared, and the result is a grid maximum.** The model declares the search
grid's **lower endpoint**, its **upper endpoint**, its **granularity** and its **stopping rule**, and
the value carries all four. `C*` is therefore **the greatest feasible point the model actually
evaluated** — resolved no more finely than the granularity, and bounded by the endpoints. **No
interpolation between evaluated points and no extrapolation beyond the upper endpoint is evaluated
evidence**, and neither may be presented as one. **The declared grid includes `C = 0` as its lower
endpoint**, with `modelled_execution_cost(0)` equal to zero, because deploying nothing incurs no
modelled execution cost.

**A non-monotone cost function is swept, never stopped at.** Where the model declares
`modelled_execution_cost` monotone non-decreasing in `C`, the search may stop at the first infeasible
point. Where it does not, the declared rule must evaluate **the whole declared domain** and return the
**greatest** feasible point in it: stopping at the first infeasible point on a non-monotone function
returns a different and smaller answer than a full sweep, so the two rules are **not
interchangeable**, and the model states which one it used.

**How capital becomes a schedule is declared, or the modelled leg is not determined.** The model
declares the mapping from a capital level `C` to the **order and trade schedule** it evaluates — how
`C` becomes per-security order sizes across this version's recorded trade population, spread over the
declared execution horizon and capped by the declared participation limit. **Without that mapping
`modelled_execution_cost(C)` is not a function of `C` at all**, and a capacity computed without a
declared mapping is **refused rather than reported**.

**Both cost legs are BPS, and they must share a basis.** `C` is **USD** deployable strategy capital;
**`modelled_execution_cost(C)`, `observed_execution_cost` and `cost_tolerance` are all BPS**, so the
difference and the tolerance are dimensionally consistent and the comparison is BPS against BPS.
**Two legs computed on different reference prices, side conventions, aggregation methods or
weightings are not comparable**, and the value is **refused rather than computed across an
incomparable basis**.

**`observed_execution_cost` is the version's realized `slippage.aggregate` over the same window**,
on the same named reference and the same side convention §12.3 fixes. **The costs-already-in-the-fill
rule of §12.4 holds unchanged**: the observed leg is taken from actual fills and is never re-charged,
and the modelled leg is a **hypothetical** which — per §12.4 — states its assumptions explicitly and
is **never placed in a series with realized results**.

**D2.7 Every required input, named.** A capacity value is admissible only when **every applicable
input** is present, each carrying its own `DataProvenance` and its own `as_of`:

| # | Required input | Notes |
|---|---|---|
| 1 | **per-security traded volume history** over the evaluated window, at the declared bar frequency on the declared calendar | from a **qualified provider**. **G1 is OPEN and no provider is selected**, so this input does not exist today |
| 2 | **per-security price history** over the same window, frequency and calendar | aligned to exactly the boundaries the trade population used |
| 3 | **the recorded order and fill history** of this exact version over the window | the `ExecutionQuality` records; the observed cost leg is computed from these and from nothing else |
| 4 | **a declared participation limit** | the maximum fraction of a security's traded volume the model assumes may be taken in one session. **A declared parameter, never derived from the outcome it produces** |
| 5 | **a declared execution horizon** | the number of sessions over which one position may be built or unwound. Declared |
| 6 | **a market-impact function** | with a declared functional form **and** a declared calibration identity, whose calibration is itself a recorded, reproducible research artefact |
| 7 | **a declared cost tolerance** | in `BPS`, on the §12.3 `slippage` reference and side convention |
| 8 | **borrow availability history** for any short-side limb | from a **record**, and **never inferred from price** — Area 13's invariant is carried unchanged. **G5 is OPEN** |
| 9 | **the portfolio-overlap set** | the other strategy versions holding the same securities over the same window. Two versions competing for one security's liquidity do not each receive all of it |

**Applicability is part of the requirement, and two of the nine are conditional.** **Input 8 is
required only where the evaluated trade population contains short exposure.** A purely long
population has no short-side limb, so borrow history is **`NOT_APPLICABLE` to the request** and **its
absence does not block admission** — requiring borrow evidence of a long-only version would make
capacity permanently unobtainable there for a reason that has nothing to do with capacity. **Input 9
is satisfied by a *determined* set, and a determined set may be empty**: *no other version held these
securities over this window* is an answer, and it is not the same fact as *nobody looked*. **An
undetermined overlap set is a missing input; an empty determined one is not.**

**The fill record is whatever actually produced it, and it is never relabelled.** Input 3 is this
exact version's recorded order and fill history, and a **`ResearchRun` consumer supplies it from an
authorized research run**, whose fills are **`BACKTEST_SIMULATED` — hypothetical, never realized, and
never broker fills**. That **satisfies the interface without implying a broker execution**: the
provenance travels with the value, a capacity resting on simulated fills is **labelled as resting on
them**, and it is **never presented as a capacity measured from real executions**. `BROKER_REPORTED`
fills would be a different provenance carrying a different claim, and the two are never merged into
one series.

**D2.8 Provenance, freshness, time alignment and point-in-time admissibility.**

| | |
|---|---|
| **provenance is carried, never assumed** | every input declares its own `DataProvenance`. **A capacity computed over `SYNTHETIC` inputs is a synthetic illustration and is labelled as one**; it is never presented as a measured capacity |
| **freshness** | §3.1 governs unchanged, and the value reports the **oldest** required input's age against **that input's own** contract |
| **alignment** | every input is aligned to exactly the window boundaries and the calendar the trade population used. **Two inputs on two calendars are not aligned by rounding** |
| **information-set profile** | **declared, never inferred.** Where any input is provider-derived, the value declares `PROVIDER_REALISTIC_PIT`. **`PUBLIC_PIT` is not reachable from provider-derived price data** — Sharadar price origin is `PROVIDER_DERIVED` under `Q7`, which stays `PUBLICLY_UNRESOLVED` |
| **model qualification** | the model carries a **recorded qualification identity**: model identity, calibration identity, the locked evaluation set it was assessed on, the assessment date, and the **human governance decision** that admitted it. **No model qualifies itself**, and no capacity value is admitted from an unqualified one. **A qualification is a recorded *positive* decision, and the existence of an assessment record is not one**: a record that **refused** the model, one that has **expired** under its own stated validity, and one **granted for a different model identity, calibration identity, evaluation set or window scope** are each **not a qualification for this request**. **Nothing is qualified by having been looked at** |

**D2.9 Portfolio overlap, and one arithmetic that is refused.** Capacity is reported **per strategy
version**. **Per-version capacities are never summed into a portfolio capacity**: overlapping
holdings mean the sum overstates what the market would absorb. A portfolio-level capacity is a
different metric, is **not defined by this ADR**, and **constructing one by addition is refused**.

**D2.10 Cost treatment, precision and the limitation set.**

| | |
|---|---|
| **cost treatment** | `NET_ALL_COSTS`. A capacity computed gross of costs answers nothing, and §12.3's cost-treatment rule applies to it as to every economic metric |
| **declared precision is not claimed resolution** | the model declares its **search domain and granularity**, and the value carries them as stated assumptions. A capacity displayed to two decimal places from a coarse search grid is a display scale, **never a claim of that resolution**, and the value is **a maximum among the points actually evaluated** rather than over the continuum |
| **it is backward-looking** | it states what the evaluated window's liquidity would have absorbed. **It is not a forecast**, and it carries no claim about future liquidity |
| **it is relative to this version's own execution** | the ceiling is that version's realized cost plus the tolerance, so **poor observed execution mechanically raises the reported capacity**. The number is **not comparable across versions of differing execution quality**, and it is **not a profitability capacity and not a risk or allocation limit** |
| **it carries no confidence claim** | unless the qualified model supplies a declared uncertainty, which is then displayed |
| **it is a model output, not a measurement** | a **hypothetical** under §12.4, labelled as one wherever it appears |

**D2.11 Behaviour when inputs or model qualification are absent — the operative half today.**

| Situation | `availability` | `reason` |
|---|---|---|
| any required input of §D2.7 absent | `NOT_YET_AVAILABLE` | `UPSTREAM_INPUT_MISSING` — **the state today** |
| no capacity model exists | `NOT_IMPLEMENTED` | `PRODUCER_NOT_IMPLEMENTED` |
| a model exists and its qualification is not recorded | `UNEVALUATED` | `NOT_YET_ASSESSED` |
| a model exists and may not run | `NOT_AUTHORIZED` | `PRODUCER_NOT_AUTHORIZED` |
| a qualification record that **refuses** the model | `NOT_AUTHORIZED` | `PRODUCER_NOT_AUTHORIZED` — **a refused model is not an unassessed one** |
| a qualification that has **expired**, or was granted for a different model, calibration, evaluation set or window scope | `UNEVALUATED` | `NOT_YET_ASSESSED` — **assessed elsewhere is not assessed here** |
| an input is older than its freshness contract | `STALE` | `UPSTREAM_INPUT_STALE`, value carried |
| the window is only partly covered | `PARTIAL` | `EXTENT_PARTIALLY_COVERED` |
| volume history does not cover the window for every security in the population | `INSUFFICIENT_OBSERVATIONS` | `BELOW_MINIMUM_OBSERVATIONS` |
| a qualified model and every input present | `AVAILABLE` | `NONE` |

**An unqualified model is `UNEVALUATED`, not `NOT_YET_AVAILABLE`.** The inputs may be complete and
the model may exist: what is missing is an **assessment**, and §2.1 gives that state its own word.
Collapsing it into a missing input would send a reader to look for absent data when the truth is
that nobody has judged the model.

**More than one of these can hold at once, so the gate is evaluated in a declared order and the first
unmet condition is the answer.** Producer existence, then authorization, then every **applicable**
input, then model qualification, then freshness, then extent. A missing producer is therefore never
reported as a missing input, and a stale input is never reported over an unqualified model. **This is
the evaluation order of one metric's own admission gate, and it is not a precedence rule over
availability states generally.**

**The search outcomes, and the one zero that is a measurement.** The admission gate decides whether a
value may be produced at all; these decide what a produced value **means**. They are recorded as
findings about the search rather than as further gate rows.

| Search outcome | What it establishes | `availability` | `reason` |
|---|---|---|---|
| the greatest feasible point sits strictly inside the declared grid | a **grid maximum at the declared granularity** — capacity lies at that point, resolved no finer, and nothing is claimed between evaluated points | `AVAILABLE` | `NONE` |
| **no positive evaluated point is feasible, and `C = 0` is** | a **computed zero**: no positive capital level the model evaluated stayed within tolerance. It is a **measurement over a qualified calculation**, it **carries the value zero**, and it is read **at the grid's resolution** — it says nothing about levels below the smallest positive evaluated point | `AVAILABLE` | `NONE` |
| **the highest evaluated point is still feasible** | a **lower bound, and not a maximum.** The search did not resolve an upper boundary, so the value means *at least this much* and is **never reported as the greatest capital the version could deploy** | `PARTIAL` | `EXTENT_PARTIALLY_COVERED` |
| **the feasible set is empty — even `C = 0` fails** | **no capacity exists under this configuration.** It arises only where `observed_execution_cost + cost_tolerance < 0`, so the version's own fills beat the reference by more than the tolerance allows and no non-negative modelled cost can meet the ceiling. **The greatest admissible `C` names nothing**, the value is **absent**, and it is **never rendered as zero** | `NOT_APPLICABLE` | `NOT_DEFINED_FOR_SUBJECT` |

**A returned maximum is a maximum within the evaluated grid, and never more than that.** An
infeasible search is not automatically a zero, a feasible upper endpoint is not a resolved maximum,
and neither gap is closed by interpolating, extrapolating or refining after the fact.

**So the blanket claim narrows to the one it was defending: no absence is ever rendered as zero.** A
missing input, a missing producer, an unqualified model, a stale or partial input and an empty
feasible set each carry **no value at all**, exactly as §4.1.2 requires, because a zero standing in
for a missing capacity renders identically to a real one. **A computed zero is a different thing
entirely** — §4.1.2 holds that a producer which ran and measured zero has answered the question, and
the second search-outcome row is exactly that case. **The forbidden zero is a substituted one, never
an arithmetic one.**

**D2.12 Minimum observations.** **The full evaluated window of session volume history, for every
security in the trade population** — a count derived from the request rather than a fixed number,
in the manner §12.3 already permits for `coverage`. Below it, `INSUFFICIENT_OBSERVATIONS` with
`BELOW_MINIMUM_OBSERVATIONS`.

**D2.13 PROPOSED MEASUREMENT DECISIONS.**

| Parameter | Proposed disposition |
|---|---|
| **the meaning** — cost-tolerance capacity against the version's own observed execution cost | **PROPOSED.** It anchors capacity to a baseline this repository already records rather than to an assumed benchmark cost |
| **participation limit, execution horizon, impact function, cost tolerance, search domain, granularity, stopping rule and the capital-to-schedule mapping** | **DECLARED BY THE QUALIFIED MODEL AND DISPLAYED WITH THE VALUE.** This ADR fixes **no numeric value for any of them** — choosing one here would be inventing a policy in a contract |
| **a computed zero is a measurement, and an empty feasible set is not a zero** | **PROPOSED.** The forbidden zero is a substituted one; an arithmetic one is an answer |
| **the value is a grid maximum, and a feasible upper endpoint is a lower bound** | **PROPOSED.** A search that did not resolve its boundary says so rather than reporting a maximum |
| **per-version reporting, with summation refused** | **PROPOSED** |

**No capacity value is claimed to be obtainable today.** **G1 is OPEN**, no provider is selected, no
volume or price history is held, no market-impact model exists, no calibration exists and no model
qualification exists. **Defining capacity does not make one computable**, and this ADR asserts no
capacity number for any security, strategy or portfolio.

---

## 3. Worked examples — synthetic, and qualifying nothing

**Every number below is invented for arithmetic demonstration.** No real security, no real fill, no
provider row, no calibrated model and no real strategy appears. **These examples calibrate no model,
qualify no provider, establish no production capacity and are not evidence about any strategy.**

### 3.1 The tail loss, computed by hand

Take one strategy version with exactly **30** eligible closed observations at evaluation point `P`.
With `q` at `0.10`, `k` is `ceil(0.10 * 30)`, which is **3**. Sorted ascending, the three most
adverse are:

```text
r(1) = -3.10 R      r(2) = -2.40 R      r(3) = -2.00 R
strategy.tail_loss  =  (-3.10 + -2.40 + -2.00) / 3  =  -7.50 / 3  =  -2.50 R
```

**Three different numbers come out of one population, and they answer three questions:**

| Quantity | Value | The question it answers |
|---|---|---|
| `strategy.tail_loss` | **−2.50 R** | when this version went wrong, how wrong |
| the worst single observation | **−3.10 R** | what is the single worst thing that happened |
| `expectancy.r`, over all 30 with a total of `+9.00 R` | **+0.30 R** | what does an average trade return |

**A version can carry a healthy expectancy and a severe tail at once**, which is why one number does
not stand in for the other.

### 3.2 The tail is selected by ordering, not by sign

A version whose three most adverse eligible observations are `+0.10 R`, `+0.15 R` and `+0.20 R`
reports a `strategy.tail_loss` of `+0.15 R`, `AVAILABLE` with `NONE`. **Even the worst decile made
money**, which is a result and not a failure to compute one. Under a losses-only population the
value would have been undefined instead.

### 3.3 Ties need no tie-break for the value

If `r(3)` and `r(4)` both equal `−2.00 R`, either may be taken as the third member and the mean is
`−2.50 R` in both cases, because the tied values are equal. **The value is deterministic without a
tie-break rule**; the declared ordering exists so that a listing of which observations formed the
tail is reproducible.

### 3.4 Future observations change nothing at or before a point

With the population of §3.1 fixed at `P`, appending a thirty-first closed trade at `−9.99 R` leaves
the value at `P` at **−2.50 R**, and moves only points after `P`. **Replacing every observation
after `P` — with any values at all — leaves every value at or before `P` unchanged.**

### 3.5 Insufficiency is not a zero

| Eligible observations at `P` | Result |
|---|---|
| 30 | the computed statistic |
| 29 | `INSUFFICIENT_OBSERVATIONS` / `BELOW_MINIMUM_OBSERVATIONS`, **value absent** |
| 0 | `INSUFFICIENT_OBSERVATIONS` / `BELOW_MINIMUM_OBSERVATIONS`, **value absent** |
| 30, of which the three most adverse are `−0.10`, `0.00` and `+0.10` | `AVAILABLE` / `NONE`, value `0.00 R` — **a measured zero** |

**The last two rows render identically to each other only if the contract is broken**, which is the
distinction this row set exists to hold.

### 3.6 Capacity — the admission gate, illustrated

**The arithmetic shape**, with placeholder values that belong to no security:

```text
observed_execution_cost      8.00 bps      from actual fills, over the evaluated window
declared cost_tolerance      4.00 bps      a model parameter, displayed with the value
admissible modelled ceiling  12.00 bps

modelled_execution_cost at C = 250,000 USD  =  11.40 bps   within the ceiling -> admissible
modelled_execution_cost at C = 300,000 USD  =  12.80 bps   above the ceiling  -> refused

C*  =  250,000 USD, on a declared search grid of 50,000 USD
```

**The declared grid is 50,000 USD, so the value's resolution is 50,000 USD**, whatever display scale
it is rendered at. **This is not a capacity for anything.** There is no security, no volume history,
no calibrated impact function and no qualified model behind those numbers.

**The gate, applied to today's actual state:**

| Input state | Resulting value |
|---|---|
| no volume history, no price history, no impact model, no qualified model — **today** | `NOT_YET_AVAILABLE` / `UPSTREAM_INPUT_MISSING` |
| every input present, model exists, qualification not recorded | `UNEVALUATED` / `NOT_YET_ASSESSED` |
| every input present, model qualified | `AVAILABLE` / `NONE` |

**Today's row is the first one, and it is exactly what the merged implementation already renders.**
This ADR therefore changes no current rendering; it states what would have to become true before the
third row could ever be reached.

---

## 4. Alternatives considered

### 4.1 The tail-loss statistic

| Alternative | Disposition |
|---|---|
| **the worst single closed trade**, the minimum `r_multiple` | **rejected.** One order statistic, moved entirely by one outlier, and carrying nothing about the shape of the tail. It is also the quantity a tail loss is most often confused with, so adopting it would make the confusion the definition |
| **an empirical quantile with an interpolation convention** | **rejected — and not for being non-deterministic.** A quantile whose convention is **declared** is perfectly deterministic and yields one number under one `metric_id`; nearest-rank, linear and Hazen differ from **each other**, so the real cost is that this contract would have to fix one further convention and hold every later implementation to it. **The operative reason is the second**: at thirty observations a fifth percentile sits between the first and second order statistics, so nearly all of its content is **one** observation — the thin-support weakness the tail statistic exists to avoid |
| **conditional tail expectation over `ceil(q * n)` order statistics** | **RECOMMENDED.** No interpolation rule is needed at all, the selection is an integer count, the value averages several observations, and it degrades predictably as the population changes |
| **a parametric value-at-risk from a fitted distribution** | **rejected.** It requires a distributional assumption nobody has evidence for, and a fitted tail is least reliable exactly where the metric is looking. It would also need a model qualification of its own, for a quantity the records can answer directly |
| **the rolling maximum drawdown of the version's trade-sequence equity** | **rejected.** That quantity already exists as `drawdown.rolling_max`. A second name for it would be precisely the drift §12.2 forbids |

### 4.2 The tail-loss window

| Alternative | Disposition |
|---|---|
| **a calendar window**, for example sixty-three sessions | **rejected.** A version that traded twice in a quarter would produce a two-observation tail under a quarterly heading, and the observation unit for a version-scoped trade statistic is closed trades |
| **the trailing 30 eligible closed trades** | **RECOMMENDED.** It reuses §12.3's own declared minimum rather than inventing a number, and it shares `expectancy.r`'s eligibility rule. **It does not make the two share a window** — §12.3 declares none for expectancy — and **a reused minimum is no evidence that three tail observations are adequate** |
| **since inception** | **rejected.** Area 5 requires a **rolling** measure, and a since-inception statistic never forgets a regime the strategy has left |

### 4.3 Capacity

| Alternative | Disposition |
|---|---|
| **a participation-limit liquidity screen** — participation fraction times average daily volume times price | **rejected.** It is a liquidity screen rather than a capacity: it says nothing about execution cost, so it would report a number with no execution meaning. It also still requires volume history, so it is not even cheaper to obtain |
| **substituting strategy capital, buying power, gross exposure or an allocation limit** | **rejected, explicitly.** Four different quantities, each already displayed under its own name (§D2.4). Substituting one renders one number twice under two meanings, and would never move when liquidity moved |
| **leaving capacity undefined and permanently unavailable** | **rejected.** Area 4 names it as a *Presents* requirement, so leaving it undefined means the requirement can never be closed — and the next implementation cycle would invent a definition on a screen, which is the failure this ADR exists to prevent |
| **a fully specified qualified-model interface with an admission gate** | **RECOMMENDED.** It defines the quantity precisely, names every input, and makes it structurally impossible for a capacity to appear without the evidence that makes it meaningful |

---

## 5. Consequences

### 5.1 What becomes true on acceptance

| | |
|---|---|
| **two §12.3 rows exist** | both quantities gain a formula or rule, a unit, a denominator or an explicit `n/a`, a basis, a minimum-observation rule and a stated unavailable outcome — the eight §12.1 requirements, met |
| **the two reported contract gaps are closed** | *as contract gaps*. **Neither measure becomes implemented**, and capacity remains blocked on data as well |
| **Area 4 and Area 5 gain acceptance criteria** | so a later implementation cycle can be checked against something |
| **the ambiguity that let two implementations diverge is removed** | one population, one window, one statistic, one sign convention, one admission gate |

### 5.2 What does not change

**No read-model schema version changes.** `strategy.tail_loss` already lives in
`StrategyHealth.payload.drift[]` and `strategy.capacity` already lives on the strategy and research
payloads; **no field is added, removed, renamed or retyped**, so §5.2's per-read-model versioning is
untouched. **`PerformanceSeries` and `StrategyPerformance` stay at `v3`**, where the merged C5
completion follow-up placed them, and every other read model stays where it was.

**No closed vocabulary is extended.** Every state and reason this ADR uses is an existing
`AvailabilityState` and `FieldReasonCode` member, and every pairing is one §4.1.1 already permits.
**`AVAILABLE`, `NOT_YET_AVAILABLE`, `NOT_IMPLEMENTED`, `NOT_AUTHORIZED`, `UNEVALUATED`, `STALE`,
`PARTIAL` and `INSUFFICIENT_OBSERVATIONS` are reused as they stand**, and no new member is proposed.

**The recommended sign convention matches what is already produced.** §12.1's loss-negative rule and
the merged synthetic tail-loss values agree, so **no fixture value is contradicted** by D1.4 and
none is changed by this ADR.

**Nothing else moves.** Book economics, entry facts, add-stage facts, R denominators, strategy
versions, risk records, health states, health-transition rules, the ADR-0026 Brain boundary, the
ADR-0030 reference-resolution rules, the ADR-0031 owning-area rules, the metric dictionary's other
rows, provider selection, gate states and every safety boundary are **unchanged**.

### 5.3 The dictionary-version obligation, placed rather than performed

**`metric_definition_version` is `metrics.v1` and is not changed by this ADR.** This is a
documentation cycle: it produces no value under either row, and changing a runtime constant is
outside its scope.

**The obligation is recorded for the implementation cycle that first produces a value.** Synthetic
values already exist for `strategy.tail_loss` under `metrics.v1` that were **not** computed under
any declared rule. So the cycle that first computes it under this row **must advance
`metric_definition_version`**, because §12.2 forbids comparing two values sharing a `metric_id`
across dictionary versions without both displayed — and pretending the old fixture numbers obeyed
this rule would be a false claim about how they were produced. **Fixture-byte equality is not a
compatibility proof**, and no such proof is offered here.

### 5.4 What stays open

```text
rolling tail losses -- IMPLEMENTATION:            NOT AUTHORIZED / NOT IMPLEMENTED
strategy capacity -- IMPLEMENTATION:              NOT AUTHORIZED / NOT IMPLEMENTED
strategy capacity -- REQUIRED INPUTS:             DO NOT EXIST
capacity model:                                   DOES NOT EXIST
capacity model qualification:                     DOES NOT EXIST
C5:                                               NOT COMPLETE
full Cockpit V1:                                  INCOMPLETE
C10:                                              NOT STARTED / NOT AUTHORIZED
G1 / G2:                                          OPEN / OPEN
G5:                                               OPEN
provider selected:                                NONE
backtesting:                                      NOT STARTED
Phase 3:                                          NOT COMPLETE
CONTROL:                                          DEFERRED
live trading:                                     HARD-DISABLED
```

---

## 6. Implementation acceptance criteria

**These are the criteria a later, separately authorized implementation cycle must satisfy.** Listing
them authorizes none of that work.

### 6.1 For the rolling tail loss — an Area 5 / C7 cycle

1. The value is computed over **closed trades of one exact strategy version** carrying a recorded
   `risk.initial_planned`, and over **no other population**.
2. The population **includes profitable observations**; the tail is selected by **ordering**, and a
   positive result renders `AVAILABLE`.
3. The statistic is the **mean of the `k` most adverse observations**, with `k` equal to
   `ceil(q * n)`, and with **no quantile interpolation anywhere in the implementation**.
4. The window is the **trailing 30 eligible closed trades**, and its **observation unit is displayed
   as closed trades**, never as sessions or periods.
5. **No observation after a point's cutoff contributes to that point**, and a regression test proves
   the strong form: replacing every later observation changes no earlier value.
6. Below 30 eligible observations — **zero included** — the value is `INSUFFICIENT_OBSERVATIONS` with
   `BELOW_MINIMUM_OBSERVATIONS` and **carries no value**.
7. A computed **zero renders `AVAILABLE`**, distinctly from insufficiency.
8. Closed trades excluded for a missing or zero initial planned risk are **counted**, and the result
   is `PARTIAL` with `UPSTREAM_INPUT_MISSING` **naming how many**.
9. The screen displays the **window, the population, the tail fraction and the observation count**
   beside the value.
10. **No health-state transition is caused, created or implied** by the value.
11. `metric_definition_version` is **advanced** at the first production of a value under this row.

### 6.2 For strategy capacity — an Area 4 / C5 cycle

1. **No capacity value is produced unless every applicable required input is present**, each with
   its own provenance and as-of — **borrow history is required only where the population carries
   short exposure**, and a **determined but empty** portfolio-overlap set satisfies its input.
2. **No capacity value is produced from an unqualified model**; an unqualified model renders
   `UNEVALUATED` with `NOT_YET_ASSESSED`.
3. **No capacity field is ever filled from strategy capital, buying power, available cash, gross
   exposure or any limit**, and a governance test asserts it.
4. **No absent capacity is ever filled with zero**, and a **computed** zero — no positive evaluated
   capital level within tolerance — renders `AVAILABLE` as the measurement it is.
5. The value declares its **search domain, granularity and stopping rule**, is reported as a
   **maximum among the points actually evaluated**, renders a still-feasible upper endpoint as
   `PARTIAL` and **a lower bound rather than a maximum**, and renders an **empty feasible set** as
   `NOT_APPLICABLE` with `NOT_DEFINED_FOR_SUBJECT` and **never as zero**.
6. The value is **labelled relative to this version's own observed execution**, so it is never read
   as a profitability capacity, a liquidity ceiling or a risk or allocation limit.
7. **No capacity is produced from an assessment record that refused the model, has expired, or was
   granted for a different model, calibration, evaluation set or window scope.**
8. The value displays its **model identity, calibration identity, qualification record, participation
   limit, execution horizon, cost tolerance and search granularity**.
9. The value declares `NET_ALL_COSTS` and its **information-set profile**, and never `PUBLIC_PIT`
   over provider-derived prices.
10. **Per-version capacities are not summed**, and no portfolio capacity is derived by addition.
11. A capacity computed over synthetic inputs is **labelled synthetic** and is never presented as a
   measured capacity.
12. `metric_definition_version` is **advanced** at the first production of a value under this row.

---

## 7. What this decision does not do

```text
implements NOTHING                          authorizes NOTHING
computes no tail loss                       computes no capacity
creates no module under src/                creates no read-model field
changes no read-model schema version        changes no metric_definition_version
extends no closed vocabulary                changes no fixture, value or component
changes no book economics                   changes no entry or add-stage fact
changes no R denominator                    changes no strategy version
changes no health state or transition rule  changes no risk limit or policy value
selects no provider                         acquires no market data
calibrates no model                         qualifies no model
runs no backtest                            claims no alpha
closes no gate                              completes no cycle and no area
```

**It does not complete C5**, it does not implement either measure, and it does not make a capacity
obtainable. **Defining a measurement is not performing it**, and **acceptance of this contract,
authorization of an implementation, qualification of real inputs or a model, and any eventual
operational use are four separate gates** that are never collapsed into one.

**Run A completed once on 2026-09-04 and a retry is NOT AUTHORIZED. Run B is NOT RUN / NOT
AUTHORIZED**, earliest 2026-09-12 and at least eight calendar days after Run A; **eligibility is not
permission**. The **combined assessment is NOT RUN / NOT AUTHORIZED**. **P1–P9 are UNEVALUATED** and
**data correctness is NOT ESTABLISHED**. **G1 and G2 are OPEN**, **G3 is CLOSED only within the
accepted personal-use scope**, and **G4–G7 are OPEN**. **No provider is selected**, **backtesting is
NOT STARTED**, **Phase 3 is NOT COMPLETE**, **ADR-0005 is PROPOSED**, **INC-0002 is OPEN**,
**CONTROL is DEFERRED**, **live trading is HARD-DISABLED**, and the **Brain runtime and every
research and feedback automation are NOT IMPLEMENTED / NOT AUTHORIZED**.
