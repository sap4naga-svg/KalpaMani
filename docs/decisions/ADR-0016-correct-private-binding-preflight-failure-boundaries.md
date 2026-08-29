# ADR-0016 — Correct the Sharadar Private-Binding Preflight Failure Boundaries

**Status:** **Accepted — effective on the merge of the pull request that introduces this ADR.**
Until that merge it is proposed and carries no authority.
**Date:** 2026-08-29
**Deciders:** Project owner (human governance)
**Supersedes:** the **live failure-classification semantics** of
[ADR-0015](ADR-0015-implement-the-dormant-sharadar-private-binding-preflight.md), and nothing else.
Specifically: the single `REFUSED_CREDENTIAL` outcome that covered the secret-identifier source, the
local SDK and client construction, and the one `GetSecretValue` call; and the stage list that named
those three as one stage. **ADR-0015 is not edited.** It is the immutable record of the decision that
was accepted, and the defect corrected here is a defect in what that decision produced, not a
retraction of it. Every other property ADR-0015 established — the singleton authorization, the
operator flag, the identifier staying out of `argv`, the fixed environment-variable name, the profile
and region pins, the governed identity gate, the licensed-bucket output, offline-composition-only
behaviour, the allowlisted output vocabulary and the zero-activity guarantees — is untouched and
re-verified here.
**Superseded by:** —
**Relates to:** [ADR-0007](ADR-0007-cloud-first-research-data-plane.md) (the governed AWS foundation
and its identity gate), [ADR-0009](ADR-0009-sharadar-provider-realistic-implementation.md) (the
credential contract this boundary hands into),
[ADR-0011](ADR-0011-implement-the-licensed-s3-research-object-store.md) (the licensed store),
[ADR-0014](ADR-0014-implement-the-dormant-sharadar-qualification-composition-root.md) (the offline
composition this preflight calls),
[ADR-0015](ADR-0015-implement-the-dormant-sharadar-private-binding-preflight.md) (the slice corrected)
**Authority:** Blueprint V3.0 §11, §17, §19 · CLAUDE.md §4.4, §4.5, §4.21, §4.22, §4.24, §7, §8

---

## 1. Context

ADR-0015 was accepted and merged as PR #22. It was written, reviewed and validated synthetically, and
it had never been run. Two authorized operator attempts were then made against the real governed
foundation, and between them they found something no synthetic test had been shaped to find.

### The two attempts

| | |
|---|---|
| **First attempt** | refused with `REFUSED_IDENTITY`. The AWS identity gate did not pass. This is the gate behaving exactly as designed: nothing later ran, no state was read, no identifier was resolved and no credential was sought |
| **Operator action** | the owner refreshed the approved AWS SSO session. This is session maintenance the owner governs (CLAUDE.md §4.20), not a change to this repository |
| **Second attempt** | passed the profile pin, the identity gate and licensed-bucket resolution, and then refused with `REFUSED_CREDENTIAL` |

`REFUSED_CREDENTIAL` reads as one thing: the private credential could not be retrieved. An operator
who read it would go and look at Secrets Manager, at the secret, at the IAM policy on the role — at
the credential boundary, because that is what the sentence names.

### What a read-only diagnostic then established

* the operational project virtual environment contains **neither `boto3` nor `botocore`**;
* `_secrets_client()` performs `import boto3` **inside its own function body**;
* that construction sat **inside the same broad exception boundary** that mapped every failure in the
  stage to `REFUSED_CREDENTIAL`;
* therefore the constructor raised `ModuleNotFoundError` and the refusal was produced **before any
  client existed**;
* therefore **no `GetSecretValue` request could have been issued**, and none was;
* and the secret-identifier source was **not separately classified**, so whether it was configured at
  all, and whether what it produced was usable, **remains unknown** — the run cannot say, and this ADR
  does not guess.

### Two findings, and only one of them belongs in this repository

**An operational-environment drift finding.** A runtime dependency this repository has declared since
[ADR-0011](ADR-0011-implement-the-licensed-s3-research-object-store.md) — `boto3>=1.36.0,<2.0`, still
declared, still correct — is absent from the operational virtual environment. That is a fact about a
machine, recorded here as evidence. Synchronizing that environment is a **separate action and is not
authorized by this ADR**, and it is deliberately not performed by the pull request that introduces
this ADR: installing the package would have made the symptom disappear while leaving the defect that
misreported it in place, on a path that only runs when something has already gone wrong.

**An implementation defect.** A local dependency failure was reported as a private-credential
failure. That is a defect in this repository, it is what this ADR corrects, and it would have
misdirected an operator on any machine, drifted or not.

### Why the wrong label is worse than an unhelpful one

The refusal was not merely vague. It was **wrong in a specific direction**: it named a boundary that
had not been reached, and it implied a request had been sent to AWS when none had been. A refusal
that points at the credential sends an operator to inspect a secret, a policy and an account — the
three things an operator should touch least often and most carefully — for a problem that was a
missing local package. And a report implying a request occurred is an unwitnessed claim about
external activity, which is the class of claim this repository holds to a higher standard than any
other.

### The owner's authorization, and its exact boundary

> I authorize a synthetic/local correction slice for the ADR-0015 private-binding preflight. It may
> introduce closed, sanitized distinctions between secret-identifier refusal, local
> dependency/client-construction refusal, and actual credential-retrieval refusal; update tests,
> documentation and audits; and record the post-merge correction through the repository's governed
> decision mechanism.
>
> This authorization covers code, tests, documentation, audits and synthetic/local validation only.
> It does not authorize installing dependencies into the operational environment, AWS activity,
> Secrets Manager calls, Terraform, another binding-preflight run, Sharadar access, S3 operations,
> qualification, ingestion, CONTROL publication, gate changes, broker/LEAN/Paper activity or live
> trading.

---

## 2. Decision

**Three stages, three closed outcomes, and each refused before the next begins.**

### The corrected vocabulary

`PreflightOutcome` keeps its closed-vocabulary discipline: fixed sentences, no interpolation of any
private or dependency-controlled text, exit status 1 on every refusal, and no word a reader could
mistake for permission.

| outcome | when | what it must never imply |
|---|---|---|
| **`REFUSED_SECRET_IDENTIFIER`** | the configured source is unavailable, raises, returns the wrong exact type, returns an empty value, or returns a value the repository's existing identifier boundary refuses | that a client was built, or that anything was asked of AWS |
| **`REFUSED_DEPENDENCY`** | the AWS SDK is unavailable, an SDK import fails, the client factory is unavailable or raises, client construction fails, the constructed client cannot serve the one operation, the secrets boundary will not import, or a dependency built after the credential fails | that a credential was requested |
| **`REFUSED_CREDENTIAL`** | one `GetSecretValue` attempt raised or was refused, the response is structurally invalid, `SecretString` is absent, a binary secret came back, or the returned string is empty or invalid under the existing credential contract | anything about the provider, the data, or whether a run should happen |

`REFUSED_DEPENDENCY` is the **renamed** `REFUSED_DEPENDENCIES` — the exact member the earlier
vocabulary already carried for dependency construction, made singular and given the client stage as
well. It is a rename, not a synonym: no alias survives, and a test asserts the plural spelling is
gone from the entry point entirely.

**A missing SDK, a failed import, a failed client construction and a missing identifier can never
map to `REFUSED_CREDENTIAL`.** That is the whole decision, stated as the thing that must not happen.

### The live stage order

1. operator authorization
2. profile contract
3. AWS-foundation identity gate
4. licensed-bucket resolution
5. secret-identifier source, and its structural validation
6. Secrets Manager SDK and client construction
7. one credential retrieval through `GetSecretValue`
8. remaining dependency construction
9. offline `preflight_qualification_composition`
10. closed result

An earlier refusal prevents every later stage, because a refusal raises. **Nothing moved forward.**
Secret-identifier access, SDK construction and credential retrieval all still sit behind the identity
and bucket gates, exactly where ADR-0015 put them — a wrong-account session still never reaches a
secret, and a failed gate still never reaches a credential.

What changed is only that stages 5, 6 and 7 are three stages instead of one, and stage 8 is named
separately from the credential it now follows.

### One identifier rule, not two

The entry point validates the identifier before it builds anything, and it validates it with
`is_usable_secret_identifier` — the secrets boundary's **own** rule, exported and imported rather
than restated. Two spellings of one rule is how a value one stage admits becomes a value the next
stage refuses, and the two would then disagree about which outcome an operator sees.

### The classification is closed and total

`SECRET_FAILURE_OUTCOME` maps every member of the boundary's `SecretRetrievalFailure` vocabulary to
an operator outcome, and a test asserts the mapping is total over that vocabulary. Two of the six are
refusals the boundary reaches **before** it calls the backend — `CLIENT_UNUSABLE` and
`SECRET_IDENTIFIER_MALFORMED` — and they map to the dependency and identifier outcomes, never to the
credential. A new failure member arriving with no entry fails the totality test before it can be
swept into "the credential failed" by a default.

### Request counts, witnessed

| outcome | identifier-source calls | secrets-client construction | `GetSecretValue` attempts |
|---|---:|---:|---:|
| authorization / profile / identity / bucket refusal | 0 | 0 | 0 |
| `REFUSED_SECRET_IDENTIFIER` | 1 | 0 | 0 |
| `REFUSED_DEPENDENCY` during secrets-client construction | 1 | 1 | 0 |
| `REFUSED_CREDENTIAL` | 1 | 1 | exactly 1 |
| completed synthetic offline preflight | 1 | 1 | exactly 1 |

**These are observed, not argued.** The synthetic suite drives the preflight with factories and a
client that count what was asked of them, and every count above is read from those counters. No test
concludes that a request happened because a particular line raised — that inference is precisely what
produced a false report against the real foundation.

`REFUSED_DEPENDENCY` also occurs at stage 8, **after** a successful retrieval; there the
`GetSecretValue` count is 1 and the outcome still names the dependency, because what failed is still
a dependency.

### The SDK stays out of the platform, and out of import time

`boto3` remains the only runtime dependency and **no module under `src/` imports it**. The one
authorized construction stays in the operator script, inside the authorized branch, inside a function
body. Every `kalpamani` import in the entry point also stays inside a function body, so the default
refusing invocation still performs no lookup, constructs nothing, opens nothing — and now provably
does not depend on the data platform being importable either, which is the class of machine this
defect was found on.

---

## 3. Alternatives considered

**Install the dependency and re-run.** Rejected, and explicitly refused by the authorization. It
would have made the symptom disappear and left the defect exactly where it was — on a path that only
executes when something has already gone wrong, and that an operator only reads when they are already
looking in the wrong place. The misreport would have waited for the next environment.

**Include the underlying exception text in the refusal.** Rejected. It would have identified the
missing package immediately, and it is the one thing this boundary must not do: an import error names
a filesystem path, a client constructor names a profile, a region or an endpoint, and a backend
exception quotes the secret name, usually the ARN and often the account. The distinction had to come
from **which closed member** is raised, not from what the failure said.

**Add one `REFUSED_DEPENDENCY` and leave the identifier folded into the credential.** Rejected. It
would have fixed the case that was actually observed and left the case that was actually *unknown*:
the second attempt could not say whether the identifier source was even configured, and folding it
into the credential is why. Two of the three distinctions were needed to answer the question the run
raised.

**Report the counts the code intended rather than the counts observed.** Rejected. A stage that
raises before its work is a stage whose work did not happen, and the only trustworthy witness of "the
backend was asked" is having watched it be asked. The counters exist so the claim is a reading rather
than an argument.

**Make `REFUSED_CREDENTIAL` the default for anything unmapped.** Kept, and narrowed until it is
correct rather than convenient: stages 5 and 6 have already excluded both pre-request causes by the
time the classifier runs, so anything the boundary can still refuse happened at or after the request.
The default is dead code while the totality test holds, and it is the honest answer if it ever runs.

---

## 4. Consequences

### What this changes

An operator reading a refusal can now tell, without inspecting anything, whether the secret identifier
was resolved, whether a client was built, and whether AWS was asked for anything. The refusal that was
observed against the real foundation would now read `REFUSED_DEPENDENCY`, and would send that operator
to the environment rather than to Secrets Manager.

### What this does not change, and does not authorize

**The operational environment is not repaired by this decision.** No dependency is installed, no
lockfile is touched, no virtual environment is altered and the declared dependency range is unchanged
— it was already correct, and a stale environment is not evidence that a declaration is wrong.
Synchronizing that environment is a **separate action under separate authorization**.

**Another binding-preflight attempt is separately authorized and has not been authorized.** Correcting
what a refusal says is not permission to produce another one. The three future events ADR-0015 named
are still three: private credential setup, a real binding preflight, and an authenticated
qualification run.

**No credential has been retrieved.** `GetSecretValue` requests issued by this repository: **zero**.
The two operator attempts refused before any request, on the evidence above.

**Nothing private is recorded by this ADR.** No credential or fragment, no AWS account identifier, no
ARN, no secret identifier, no bucket identifier, no region-plus-account pair, no provider data, no
empirical result, and no underlying exception text from either attempt.

### Standing claims that stay exactly as they were

`AcquisitionMode.QUALIFICATION` · `PROVIDER_REALISTIC_PIT` · Q7 and Q8 · `permaticker` · append-only
S3 semantics · acquisition identity · the response and run ceilings · no-resume semantics ·
three-write reporting · provider-neutral contracts · every production-ingestion boundary · the
singleton authorization capability · the operator flag · the identifier staying out of `argv` · the
fixed environment-variable name · the profile and region pins · the governed identity gate and state
read · the licensed-bucket output · `SystemClock` in the operator path · `reveal()` called **zero**
times during preflight · offline composition only · no provider-fetch operation · no
object-publication operation.

**G1 OPEN · G2 OPEN · G3 CLOSED · G4–G7 OPEN**, ADR-0005 **PROPOSED**, INC-0002 **OPEN**, Phase 3
**NOT COMPLETE**, CONTROL publication **DEFERRED**, live trading **HARD-DISABLED**.

---

## 5. Verification

Every property below is a test or an audit guard, not an intention. Synthetic and local only: no AWS
call, no Secrets Manager call, no Terraform command, no provider request, no S3 operation, and no
binding-preflight execution was performed to produce any of it.

| property | evidence |
|---|---|
| an identifier failure is its own outcome, and sends nothing | `test_an_identifier_failure_is_its_own_outcome_and_sends_nothing` |
| an identifier failure discloses neither the value nor the cause | `test_an_identifier_failure_discloses_neither_value_nor_cause` |
| a usable name and a usable ARN each reach the backend once | `test_a_usable_identifier_shape_reaches_the_backend_exactly_once` |
| a missing SDK is a dependency refusal with zero requests | `test_a_client_construction_failure_is_a_dependency_refusal` |
| a dependency failure discloses no underlying text | `test_a_dependency_failure_discloses_no_underlying_text` |
| a constructed client that cannot serve the operation is a dependency refusal | `test_a_constructed_client_that_cannot_serve_the_operation_is_a_dependency_refusal` |
| an unimportable secrets boundary is a dependency refusal | `test_an_unimportable_secrets_boundary_is_a_dependency_refusal` |
| a dependency failure after the credential is still a dependency refusal | `test_a_late_dependency_failure_is_still_a_dependency_refusal` |
| a backend refusal is a credential refusal after exactly one attempt | `test_a_backend_refusal_is_a_credential_refusal_after_exactly_one_attempt` |
| an unusable response is a credential refusal after exactly one attempt | `test_an_unusable_response_is_a_credential_refusal_after_exactly_one_attempt` |
| a valid synthetic secret completes with one attempt | `test_a_valid_synthetic_secret_completes_with_one_attempt` |
| the classification is total over the boundary vocabulary | `test_every_secrets_boundary_failure_is_classified` |
| the two pre-request failures are never credential failures | `test_the_pre_request_failures_are_never_credential_failures` |
| the four post-request failures are credential failures | `test_the_post_request_failures_are_credential_failures` |
| the outcome vocabulary is closed, with no alias | `test_the_outcome_vocabulary_is_exactly_these_members` |
| the superseded plural member is gone, not aliased | `test_the_superseded_plural_member_is_gone` |
| no pre-request refusal is worded as a credential failure | `test_no_refusal_before_the_request_is_worded_as_a_credential_failure` |
| every outcome's call counts are witnessed | `test_every_outcome_has_its_witnessed_call_counts` |
| the refusing default path needs neither the SDK nor the package | `test_the_refusing_default_path_needs_neither_the_sdk_nor_the_package` |
| the exact live stage order on the authorized path | `test_the_full_ordering_is_exact_on_the_authorized_path` |
| the identifier is untouched by every earlier refusal | `test_the_identifier_source_is_untouched_by_every_earlier_refusal` |
| `reveal()` is never called during preflight | `test_the_credential_is_never_revealed_during_preflight` |
| no provider or object-store call occurs | `test_provider_and_object_store_call_counts_remain_zero` |
| no module under `src/` imports the SDK | `test_no_module_under_src_imports_the_sdk` |
| the entry point is the only SDK client constructor | `test_the_entry_point_is_the_only_place_that_constructs_an_sdk_client` |
| the three boundaries and the count rules are stated in the status documents | `scripts/phase3_docs_audit.py` §23 |
| no status document describes a missing SDK as a credential failure | `scripts/phase3_docs_audit.py` §23 |
| no status document claims the environment was repaired or a preflight completed | `scripts/phase3_docs_audit.py` §23 |

**What this verification does not establish.** It says nothing about the provider, the data, the
secret, the account or the environment. It establishes that the three refusals are distinguishable,
sanitized and ordered, and that their request counts are what the synthetic suite observed. Whether
the identifier source is configured on any machine remains **unknown**, and this correction does not
find out.
