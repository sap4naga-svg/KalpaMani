# ADR-0039 — Two universe exclusion reasons: indeterminate attributes and unresolved corporate actions

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0039 is proposed and carries no authority.
That is a statement about the present, it will remain true of these days after any later merge, and it
is not to be rewritten as though this decision had authority before it was accepted. On merge, this ADR
becomes **ACCEPTED / IN FORCE** as **a narrow amendment of the accepted point-in-time vocabulary — two
additional members of `UniverseExclusionReason` — and nothing else**.

**Nothing was run to produce this decision.** No AWS call, no Terraform plan or apply, no read of any
licensed object, no provider request. The evidence is the accepted vocabulary, ADR-0035's design, and the
offline build implementation exercised on synthetic fixtures.

---

## 1. Context — two reasons the accepted vocabulary cannot record

[ADR-0035](ADR-0035-initial-breakout-long-research-dataset-ingestion-design.md) §3.4 and §3.6 each name a
membership outcome the accepted `UniverseExclusionReason` — `PRICE`, `MARKET_CAP`, `ADDV`, `HISTORY`,
`EXCHANGE`, `SECURITY_TYPE` — has no member for:

- **an indeterminate attribute clause.** The `tickers` snapshot carries no dated history for exchange,
  security type, listing bounds, sector or industry, so for a session before the first admissible snapshot
  revision the exchange and security-type clauses cannot be evaluated at all. Excluding such a security
  under `EXCHANGE` would assert that its exchange was wrong; admitting it on a value observed years later
  would be exactly the survivorship leak §3.4 exists to prevent. ADR-0035 proposed
  `ATTRIBUTE_UNAVAILABLE` for this, *implemented only under the ingestion gate*.
- **an unresolved corporate action.** A spinoff is recorded and never adjusted for, and every artifact
  depending on the security is excluded from the session of the first spinoff ex-date onward until the
  vendor's spinoff semantics are resolved by a later decision. None of the six accepted reasons says that.
  ADR-0035 proposed `UNRESOLVED_CORPORATE_ACTION`, *implemented under the ingestion gate, not silently*.

The offline research-build implementation merged beside this proposal needs both outcomes to be recordable,
and the accepted vocabulary is guarded: a governance test holds that neither member exists in
`kalpamani.data.contracts.vocabulary` until a contract ADR adds it. The implementation therefore keeps a
**build-local** closed vocabulary (`production/sharadar/universe.py`, `BuildExclusionReason`) whose six
accepted members mirror the accepted enum member for member and whose two further members are these; every
membership row records which vocabulary its reason belongs to (`accepted` or `proposed-adr-0039`). The
accepted contract is neither redefined nor widened by that mirror.

## 2. Decision

**`UniverseExclusionReason` gains two members, with exactly these semantics:**

```text
ATTRIBUTE_UNAVAILABLE          no attribute revision admissible at decision_time(d) allows the exchange or
                               security-type clause to be evaluated; the security is excluded because the
                               clause is indeterminate, not because it failed
UNRESOLVED_CORPORATE_ACTION    a spinoff (or another action a later decision names) with an ex-date on or
                               before d is admissible; the security is excluded from that session onward
                               until the action's semantics are resolved by a later decision
```

Consequences:

1. **The build-local mirror retires on effectiveness.** Once the members exist in the accepted vocabulary
   the build records membership rows against `UniverseExclusionReason` directly and the
   `exclusion_vocabulary` field reads `accepted` for every row; until then the mirror is the only place the
   two reasons exist, and a row carrying one says so.
2. **Nothing about the rule changes.** The clause order, the decision cutoff, the revision discipline and
   the spinoff exclusion are ADR-0035's; this ADR only makes two of its outcomes recordable.
3. **The census reports both.** ADR-0035 §3.7's history-admissibility census counts securities per session
   whose attribute revision is admissible versus `ATTRIBUTE_UNAVAILABLE`; that count is what the owner's G2
   decision reads, and this ADR does not read it for them.

## 3. Effectiveness and execution gates

- **Effectiveness**: this amendment is in force only on the independently reviewed merge of the pull
  request introducing it. The offline implementation that accompanies it uses a build-local mirror on
  synthetic fixtures only; that code existing is not this amendment being in force, and a later change
  moving the two members into the accepted vocabulary is its own reviewed pull request.
- **Execution**: acceptance authorizes no build, no ingestion and no run. Every gate ADR-0036 leaves closed
  stays closed. **G2 stays OPEN**: recording that an attribute is unavailable is not evidence that it is
  available, and the criterion G2-H names — event-dated listing and exchange sources — is untouched.
- **Scope**: nothing here amends ADR-0035's availability rules, adds a `ProviderBoundDerivation` member
  (`VENDOR_DATE_UPPER_BOUND` and `VERSION_EVIDENCE_UPPER_BOUND` stay proposed and gated, because the
  evidence they need does not exist), changes an IAM statement, a bucket policy, a Terraform declaration or
  a deployed resource, or resolves the vendor's spinoff semantics.

## 4. Rejected alternatives

- **Record indeterminate attributes as `EXCHANGE` or `SECURITY_TYPE`.** Asserts a failure nothing observed.
- **Admit a security on the current snapshot's attributes for a historical session.** The survivorship leak.
- **Record the spinoff exclusion as `HISTORY`.** Hides a corporate-action question inside a data-coverage
  reason, and a later decision resolving spinoffs could not find what to re-admit.
- **Add the members to the accepted vocabulary in the implementation pull request.** Widens an accepted
  contract silently, which is the thing a governance test guards against.

G2 OPEN; CONTROL DEFERRED; Phase 3 NOT COMPLETE; live trading HARD-DISABLED.
