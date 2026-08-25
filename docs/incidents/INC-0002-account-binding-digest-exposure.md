# INC-0002 — Account-binding digest committed while the repository was public

- **Date opened:** 2026-08-25
- **Classification:** information exposure — sensitive pseudonymous identifier
- **Severity:** medium (paper account; the value is a digest, not a credential)
- **Status:** **OPEN** — remediation pending a GitHub purge
- **Related:** [ADR-0004](../decisions/ADR-0004-deterministic-order-identity-idempotency-and-execution-lifecycle.md)
  §18; [INC-0001](INC-0001-run1-manual-cleanup-transient-short.md)

> This record deliberately contains **no** brokerage account identifier, **no**
> account-binding digest, and **no** object SHAs. The SHAs live only in the
> untracked operational request under `.runtime/support/`, so that this file
> cannot become a signpost if the repository is ever made public.

---

## What happened

`account_fingerprint()` was documented as producing a "non-reversible
fingerprint". It does not. It is an unsalted SHA-256 over a **structured,
low-entropy** brokerage account identifier: anyone holding a candidate account id
can confirm a match by recomputing it. That makes it a **pseudonymous
identifier**, not anonymised data.

Because it was treated as anonymous, a real one was pasted out of a container log
into the Phase-2 runbook and committed — while the repository was public.

## What was done

| | |
|---|---|
| Repository visibility | set to **private** (restoring CLAUDE.md §3, which had been violated) |
| Branch history | rewritten so the value is absent from **every commit** on the branch; all commits preserved |
| Emission | the digest is no longer logged, printed or committed anywhere — output says `present` / `matched` / `DIFFER` |
| Guardrails | tests assert both `describe()` methods and the mismatch message never emit it; the review-bundle builder scans and aborts |
| Root cause of the leak path | container logs flagged as sensitive: IBAutomater writes the full account id into IB Gateway window titles |

## What is still open

**A force-push does not delete anything.** The pre-rewrite commits and their
blobs remain retrievable from GitHub by SHA, through the API and the web UI, and
they still carry the value. The same is true of PR #3's description edit history,
which retains an earlier revision containing it.

While those objects exist, **the repository must stay private** — making it
public would knowingly re-expose the value to anyone who knows or guesses a SHA.

### Remediation sequence

1. Repository stays **PRIVATE**. ← current state
2. Submit the GitHub Support purge request (prepared under `.runtime/support/`,
   untracked). It names object SHAs and the PR whose body history needs purging.
   **It does not contain the value** — Support does not need it, and sending it
   would defeat the request.
3. GitHub confirms the purge.
4. Run `scripts/verify_purge.py`. It reports a verdict only, and exits non-zero
   while any object is still retrievable.
5. **Only then** ask for authorisation to make the repository public.
6. If approved, change visibility **and** CLAUDE.md §3 in the same controlled
   change, so policy and reality never disagree.

Until step 4 passes, this incident stays open and no visibility change is
proposed.

## Lesson

The digest was not a secret anyone chose to publish; it was a value nobody had
classified. "Non-reversible" was a claim about the hash function, not about the
input, and the input is a short structured identifier with very few plausible
values. A digest is only as anonymous as the space it summarises.

The second lesson is quieter: deleting a value from a branch is not the same as
deleting it from a hosting provider, and treating a force-push as remediation
would have left this closed while it was still open.
