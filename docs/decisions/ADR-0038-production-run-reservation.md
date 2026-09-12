# ADR-0038 — The production run reservation: a payload-independent, single-use claim of the run identity

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0038 is proposed and carries no authority.
That is a statement about the present, it will remain true of these days after any later merge, and it
is not to be rewritten as though this decision had authority before it was accepted. On merge, this ADR
becomes **ACCEPTED / IN FORCE** as **a narrow amendment of ADR-0037 §2's claim namespace — one additional
object class under it — and nothing else**.

**The condition above has since been satisfied.** **PR #96 merged** — merged **2026-09-12T15:10:12Z**, merge
commit **`6ddfa3601a8b14d4e0768ddd823f2c5a34927bdd`**, ordered parents **`7c83da07308eca69b9484c09edd1769ca4055abe`** then
**`61b501cfbb8b1105e11363e41b2767de5cc2aa0a`**, with a **merge tree identical to the independently reviewed pull-request head
tree** (`4e581c8b1f565d0a86f6c80d9d2279518beb7ea4`). ADR-0038 is therefore **ACCEPTED / IN FORCE** as a narrow amendment of
ADR-0037 §2's claim namespace, effective together with the offline implementation merged beside it. While the
pull request was open it was proposed and carried no authority — true then, and not rewritten. **Acceptance
authorizes no run**: every gate ADR-0036 leaves closed stays closed, the reservation has been written only by
synthetic fakes, and no IAM statement, bucket-policy statement, Terraform declaration or deployed resource
changed on the merge.

**Nothing was run to produce this decision.** No AWS call, no Terraform plan or apply, no read of any
licensed object, no provider request. The evidence is the merged production key builders and the accepted
ADRs that describe them.

---

## 1. Context — the guard the claim names cannot provide

[ADR-0035](ADR-0035-initial-breakout-long-research-dataset-ingestion-design.md) §3.1 makes an execution
identity single-use and forbids resumption; [ADR-0036](ADR-0036-production-data-plane-principals-and-trust-model.md)
§2.6 has a task refuse *an input whose run identity is already spent*. The acquisition actor is write-only
([ADR-0019](ADR-0019-write-only-acquisition-collision-policy.md)): it cannot read a ledger, list a prefix
or probe an object, so the only durable guard it can meet is a **conditional, create-only `PutObject`** on a
name that an earlier run under the same identity would already occupy.

The production claim and record names of [ADR-0037](ADR-0037-disjoint-production-bronze-namespaces.md)
bind `(payload digest, run identity, request ordinal)`. They protect request provenance exactly, and they
do **not** protect the run identity: a second attempt under a spent identity whose provider responses differ
— an unchanged snapshot re-observed a day later, a corrected page, a different plan under the same identity
— derives new digests, new claim names and new record names, meets no occupied name until the locator, and
has by then retrieved the credential, made every provider request and written every Bronze object. The
independent review of the offline processing implementation reproduced exactly that. The locator name is
payload-independent, but the locator is published **last** by design (ADR-0036 §2.4) and cannot be the
first write without inverting that design.

## 2. Decision

**Every production acquisition run makes one payload-independent, conditional, create-only write of a
run reservation before any credential is retrieved and before any provider request:**

```text
licensed/bronze/_production_claims/runs/<run-id>.json      kalpamani-production-run-reservation/v1
fields    schema_version · contract_id · run_id · plan_digest · acquisition_mode · reserved_at
ordering  after the placement release barrier (ADR-0036 §2.9), as the first S3 operation of the run,
          admitted and counted like every other; before ``GetSecretValue``; before the first request
write     one conditional PutObject, IfNoneMatch="*", SSE-S3, full-object SHA-256 -- exactly as every
          other production object; never overwritten, never deleted by the acquisition actor
```

Consequences, each of them what the write-only boundary requires:

1. **A reservation conflict (412) stops the run before any provider request**, with the closed outcome
   `RESERVATION_CONFLICT`. The identity is spent, whatever bytes a re-run would produce and whatever plan it
   carries. **No locator is published** by the losing attempt: a locator under an identity another run
   holds would be a locator under a name that is not this run's to claim.
2. **An ambiguous reservation outcome stops the run with the uncertainty preserved** —
   `RESERVATION_STATE_UNKNOWN`, `publication_state_unknown = true`, no credential, no request, no locator.
   A definitive refusal is `RESERVATION_REFUSED`. **Nothing is retried, read, adopted or resumed.**
3. **Concurrent contenders**: the conditional write is the server's decision, so exactly one contender's
   reservation succeeds; every other contender stops at clause 1 and publishes nothing.
4. **A reserved identity stays spent when later processing fails.** The reservation is never deleted (the
   actor cannot delete), so a halted run's identity is permanently retired, as ADR-0035 requires. A new
   attempt needs a new identity and a new written authorization.
5. **The preliminary spent-identity check is unchanged and stays preliminary.** The registry answer is a
   courtesy refusal before anything is spent; it does not, and is not claimed to, prevent concurrent reuse.
6. **The accounting changes by exactly one operation per run.** A complete run of `R` requests performs
   `1 + 3R + 1` conditional `PutObject` operations (reservation, three per request, locator); every path
   reports the reservation attempt as one issued operation.

**The namespace is the claim namespace, and the semantics are a claim's.** A claim binds an identity so
that no second writer can own it; the reservation binds the run identity itself. The `runs/` segment is not
a digest (a digest is sixty-four hexadecimal characters), so it can never collide with a request claim, and
the object lies inside `bronze/_production_claims/*`, which the acquisition actor's accepted grant already
admits for conditional `PutObject` and the build actor's accepted policy already denies for `GetObject`.
**No IAM statement, bucket-policy statement, Terraform declaration or deployed resource changes**; the
deletion runbook already names the prefix.

## 3. Effectiveness and execution gates

- **Effectiveness**: this amendment is in force only on the independently reviewed merge of the pull
  request introducing it. The offline implementation that accompanies it (`processing.py`) performs the
  reservation on synthetic fakes only; that code existing is not this amendment being in force.
- **Execution**: acceptance authorizes no run. Every gate ADR-0036 leaves closed stays closed — Terraform
  application, R-3 verification, image publication, task launch, the first bounded ingestion — and the
  provider-transport incompatibility and the task-side spent-identity source recorded beside the offline
  implementation are unchanged by this decision.
- **Scope**: nothing here amends ADR-0019's collision policy, ADR-0036's data-plane grants, ADR-0037's
  payload, record or locator layouts, or any qualification contract.

## 4. Rejected alternatives

- **Reserve the locator name first.** Inverts *published last*; a first-written locator would name objects
  that do not exist and would have to be overwritten, which the immutable-write policy forbids.
- **Make the claim name payload-independent.** Removes the request-provenance binding ADR-0037 relies on.
- **Rely on the registry alone.** An in-memory or ledger answer cannot prevent concurrent reuse and is
  unavailable to a task; ADR-0035's single-use rule needs a server-side decision.
- **Grant the actor a read to check for a prior locator.** Re-opens the read surface ADR-0019 removed.

G2 OPEN; CONTROL DEFERRED; Phase 3 NOT COMPLETE; live trading HARD-DISABLED.
