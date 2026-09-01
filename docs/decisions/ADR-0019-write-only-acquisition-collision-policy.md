# ADR-0019 — Write-only ADR-0018 acquisition, and fail-closed collision policy

**Status: PROPOSED — no authority until the pull request introducing it is independently
reviewed and merged.**

While that pull request is open this ADR governs nothing. It is a proposal to amend
[ADR-0018](ADR-0018-bounded-private-empirical-sharadar-qualification.md), and until it merges
**ADR-0018 as accepted is what governs**. That is the same conditional treatment ADR-0017 and
ADR-0018 were each given, and it is written down rather than assumed.

**Date:** 2026-08-31
**Supersedes:** nothing.
**Amends, upon acceptance:** ADR-0018 §4.5.3, §7.4, §9.1, §9.2, §9.3, §9.5 and §10.1 — and
nothing else.
**Does not amend:** ADR-0017, ADR-0016, ADR-0015, ADR-0014, ADR-0013, ADR-0012, ADR-0011,
ADR-0010, ADR-0009, ADR-0008, ADR-0007, ADR-0006 or ADR-0005.

---

## 1. What is unchanged by proposing this

**ADR-0018 remains ACCEPTED / IN FORCE.** This ADR proposes a narrow amendment to its acquisition
collision-resolution rule and to the arithmetic that rule feeds. Everything else ADR-0018 decided
stands exactly as accepted.

**The merged ADR-0018 offline implementation remains MERGED / DORMANT.** It is not corrected by
this proposal, and this proposal changes no line of it. **The merged implementation is not
deployable under the accepted boundary until a later implementation-correction gate is
completed.**

**ADR-0017 is not amended and not superseded.** Its entry point, its operation accounting —
exactly three PutObject, zero to three conditional HeadObject, zero object-byte reads — and its
use of the shared research object store are untouched by this ADR.

**ADR-0011's application-shape contract is unchanged.** The shared store keeps the surface it was
accepted with.

**This ADR authorizes nothing.** No code correction, no infrastructure design mutation, no
Terraform, no IAM, no deployment, no Run A, no Run B, no combined assessment, no provider request,
no S3 operation, no credential retrieval and no execution of any kind. Implementation,
infrastructure mutation and execution stay three separate gates and are never collapsed into one.

**Infrastructure remains blocked.** Accepting a corrected design is not permission to build it.

---

## 2. Context — the feasibility finding

A read-only infrastructure-feasibility reconciliation of ADR-0018 against AWS's authorization
model returned the closed classification **STOPPED_ARCHITECTURE_GAP_HEAD_REQUIRES_GET**.

ADR-0018 §10.1 requires the qualification-acquisition role to hold two properties at once:

| | |
|---|---|
| **granted** | the metadata-only collision resolution the append-only writer requires — a HeadObject issued after a conditional PutObject returns 412 |
| **withheld** | object-byte GetObject |

**AWS maps both to the same IAM action, so the two requirements are jointly undeployable.** No
faithful least-privilege policy can grant one and withhold the other.

**The prohibition was intended at the IAM layer, not only in the code.** ADR-0018 §10.1 is written
as grant language — the role *must not receive* the permission — and §10.3 rests the whole
two-role split on a compromise argument: *a compromised acquisition path cannot exfiltrate the
licensed store*, holding as *a property of the identity system, not only of the code*. An
application shape cannot carry that argument, because a compromised process holds the role's
credentials and calls whatever the role is permitted to call.

**The deletion role is not a precedent for it, and the difference is the whole point.** ADR-0018
§10.4 presents the deletion role's *can act, cannot read* as a working parallel. It is not one:
listing and deleting have their own IAM actions, so withholding object-read authority from that
role costs nothing. A metadata read has no action of its own.

---

## 3. The AWS constraint, as documented

Established from current official AWS documentation, and recorded as findings rather than
opinion:

- **HeadObject requires the s3:GetObject permission.** The API reference states, for general
  purpose buckets: *"To use `HEAD`, you must have the `s3:GetObject` permission."*
- **A GetObject for a known current object uses that same s3:GetObject permission.** Granting it
  for a collision check grants it for a full read of any key the principal knows — and an
  acquisition process knows every key it writes, because it derives them deterministically.
- **AWS exposes no independent s3:HeadObject IAM action.** The operation-to-permission mapping
  lists HeadObject against s3:GetObject, and no such action appears in it.
- **GetObjectAttributes does not solve it**, because it also requires object-read authority —
  s3:GetObject without a version id, or s3:GetObjectVersion with one.
- **No condition key distinguishes the HTTP method.** S3 authorizes by policy action, never by
  verb, so an explicit deny on the read action denies the metadata call with it. There is no
  documented condition key, access-point mechanism or request-context distinction that separates
  HEAD from GET.
- **Absence of s3:ListBucket prevents enumeration but not a known-key read.** AWS documents the
  actual effect: without it, a request for a *nonexistent* key answers 403 rather than 404. An
  existing key the principal knows is still readable.
- **The current SSE-S3 design offers no KMS permission that could be withheld.** The licensed
  bucket and the writer both use SSE-S3, deliberately, so there is no caller-side key permission
  in the path at all. Converting to SSE-KMS would not rescue the boundary either: AWS documents
  that retrieving a checksum with checksum mode enabled on a KMS-encrypted object requires
  kms:Decrypt, and the collision resolution depends on exactly that checksum — so the withheld
  permission would break the operation it was meant to permit. A missing kms:Decrypt would in any
  case be an incidental denial rather than least privilege, leaving the read action granted.
- **An application protocol without a get_object method does not remove IAM authority from a
  compromised process.** It is defense in depth over the boundary, not the boundary.

**Sources**, and no more of them than the finding needs:

- <https://docs.aws.amazon.com/AmazonS3/latest/API/API_HeadObject.html>
- <https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-with-s3-policy-actions.html>
- <https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObjectAttributes.html>

---

## 4. Decision

**The security boundary is preserved and the operation is removed.** Where ADR-0018 accepted two
requirements that AWS cannot both satisfy, this ADR keeps the one that is a security control and
drops the one that is a convenience.

### 4.1 The acquisition role

Upon acceptance, ADR-0018 §10.1 reads as follows. The qualification-acquisition role:

- **receives s3:PutObject only**, and only on its authorized object prefixes;
- **receives no s3:GetObject**;
- **receives no s3:GetObjectVersion**;
- **receives no s3:GetObjectAttributes**;
- **receives no S3 listing, copy or deletion authority**, and no CONTROL authority;
- **performs no HeadObject**;
- **performs no object-byte read**;
- retains its one governed secret retrieval, and nothing else.

**Both layers are retained, independently.** The application-level prohibition on a get_object
method stays exactly as the merged implementation already has it, and the IAM-level prohibition
stands on its own without relying on it. Neither is a substitute for the other, and removing
either is an ADR-level change.

### 4.2 Bronze collision behaviour — fail closed, compare nothing

For **every** acquisition-side conditional PutObject answered `412 Precondition Failed`:

```text
do NOT read, HEAD, inspect, compare, hash or download the occupied object
do NOT classify the occupied object as identical
do NOT return an already-present-identical disposition
do NOT retry the collided PutObject
do NOT continue the affected publication step as though it succeeded
do NOT treat the collision as evidence of a valid retained acquisition
do NOT resume from, reuse or adopt the occupied object
```

**The run fails closed on a bounded, sanitized terminal outcome.** The proposed closed member is
**BRONZE_NAME_OCCUPIED**, and its meaning is exactly what a 412 establishes and no more: *a
conditional write found this name occupied.* It carries no claim about the occupying object's
content, size, digest, origin or age, because none of those is knowable without the read this
role does not have.

**No key, digest, identifier, subject, supplied count or private value is disclosed** by the
outcome, its message, its repr or any public counter.

**A 412 does not establish that the occupied object is identical.** That is the sentence this
whole amendment exists to make true, and it is the one an implementation must not quietly soften
back.

**What is genuinely lost, stated rather than minimised.** ADR-0018's accepted design could
distinguish an idempotent re-publication from a real collision. This design cannot: both become
one refusal. The loss is bounded by a rule ADR-0018 already made — re-running a halted execution
is **not** a resume, and a refetch requires a **new explicit execution identity** — so the
disposition that disappears was never a resume mechanism. It was a diagnostic, and it cost an IAM
capability that the architecture's own compromise argument cannot afford.

### 4.3 Locator collision

The same rule, without exception:

- the locator publication stays a **conditional PutObject**;
- it issues **zero HeadObject**;
- a locator 412 **fails closed**;
- **no existing locator is inspected, verified or adopted**;
- **no success is inferred from a locator's presence**;
- the bounded locator retry permission of ADR-0018 §9.2 is **retained unchanged** — at most two
  retries, only on `THROTTLED` or `TRANSIENT`, never after an ambiguous or unclassified result.

**ADR-0018 §7.4's `LOCATOR_COLLISION` row is amended**, because it currently classifies *a locator
name occupied by different content* — and *different* is a comparison this role can no longer
make. The proposed replacement member is **LOCATOR_NAME_OCCUPIED**, meaning *the locator name was
occupied and the occupying content was not determined.* `LOCATOR_NOT_PUBLISHED`,
`LOCATOR_STATE_UNKNOWN`, `COMPLETE` and `PARTIAL` are unchanged.

**One honest consequence of retaining the retry permission.** A retry is permitted only while the
condition is unresolved, and every retry sends byte-identical content. If an earlier attempt did
in fact commit, the retry is answered 412 and now fails closed — so the run reports
LOCATOR_NAME_OCCUPIED even though a correct, byte-identical locator exists. **That is a false
negative in the safe direction**: the run never claims a locator exists when it does not, nothing
is overwritten, duplicated or corrupted, and the orphaned object stays inside the licensed
qualification prefix that prefix-based deletion already covers. Under ADR-0018 as accepted this
case resolved to *already present*; it cannot now, and the difference is recorded rather than
absorbed.

### 4.4 What a locator may truthfully claim after a Bronze collision

A Bronze BRONZE_NAME_OCCUPIED halts the run. Whatever completed before it **stays published** — a
halt is not a rollback — so the accounting must be preserved.

- A **`PARTIAL`** locator **may** be published, if and only if the reserved locator-terminal
  budget still permits its complete permitted sequence.
- It may truthfully record: the planned request count, the **completed** request count, the exact
  key, expected digest, byte count and disposition of **every object this execution actually
  published**, the plan and inventory digests, and the completeness value `PARTIAL`.
- It **must never** record the collided object as verified, retained, adopted or belonging to this
  execution, and **must never** claim its content was compared. The collided publication step is
  recorded as **not completed**, with no object reference of any kind.
- If no safe locator attempt can begin within the reserve, the closed result is
  **`LOCATOR_NOT_PUBLISHED`**, exactly as ADR-0018 §7.4 already provides. **It must not claim a
  locator exists**, and evidence is retained and unaddressable until a new execution identity is
  authorized.
- The assessor's behaviour is unchanged: a `PARTIAL`, missing, occupied, ambiguous or unverified
  locator **is refused for evaluation**.

**Inventing evidence is never the fallback.** There is no path that reconstructs an execution by
listing, probing or guessing, because adding one would reintroduce the capability this
architecture removes.

---

## 5. Isolating ADR-0018 from ADR-0017 — a requirement on the later gate, not code

**The shared research object store is not changed by this ADR, and must not be.** Its conditional
PutObject and its 412 metadata resolution are what ADR-0017 was accepted with, and removing that
resolution from the shared store would silently rewrite ADR-0017's committed accounting.

**Upon acceptance, the later implementation-correction gate is required to introduce an
ADR-0018-specific write-only publication surface** — an adapter used only by the ADR-0018
acquisition path — which:

- exposes **conditional put behaviour only**;
- has **no head_object**;
- has **no get_object**;
- **cannot be used by ADR-0017 accidentally**, structurally rather than by convention;
- **does not alter ADR-0017's accepted three-PutObject and conditional-HeadObject behaviour**;
- **does not change ADR-0011's application-shape contract** for the shared store;
- is **structurally prevented from importing or invoking the assessment read surface**.

**This is an architectural requirement for the later code correction, not code authorized by this
ADR's proposal pull request.**

---

## 6. Re-derived operation arithmetic

Derived from the zero-HeadObject rule, not substituted into the old tables.

**Acquisition operations reduce to PutObject alone.** With HeadObject at zero, object-byte
GetObject at zero, listing at zero and CONTROL at zero, the acquisition S3 total *is* its
PutObject total.

```text
Bronze PutObject        = 3 per completed request x 48 completed requests   = 144
locator PutObject       = 1 attempt, plus at most 2 retained retries        = 1 to 3
acquisition PutObject   = 144 + (1 to 3)                                    = 145 to 147
acquisition HeadObject                                                      = 0
acquisition GetObject                                                       = 0
acquisition S3 ops      = PutObject + 0 + 0                                 = 145 to 147
```

### 6.1 A successful complete run

| Operation | Count |
|---|---|
| Provider requests | **exactly 48** |
| Provider retries | **zero** |
| Bronze PutObject | **exactly 144** |
| Locator PutObject | **1 to 3** |
| **Total PutObject** | **145 to 147** |
| Conditional HeadObject | **exactly zero** |
| Object-byte GetObject | **exactly zero** |
| S3 listing | **zero** |
| CONTROL operations | **zero** |
| **Total S3 operations** | **145 to 147** |

**A successful complete run has no collision**, by construction: a Bronze 412 halts the run, so a
run that completed all 144 Bronze publications met no occupied name.

**Two successful acquisition runs: 290 to 294 S3 operations.**

### 6.2 Assessment — unchanged

Nothing in this amendment touches the assessment actor, which is *supposed* to read bytes and
whose role is unaffected by the acquisition boundary.

| Operation | Count |
|---|---|
| Total GetObject | **194** |
| Report PutObject | **1** |
| Conditional report HeadObject | **0 to 1** |
| **Total assessment S3 operations** | **195 to 196** |

### 6.3 Whole successful package

```text
two successful acquisition runs      290 to 294
one combined assessment              195 to 196
whole successful package             485 to 490
```

`485 = 290 + 195` and `490 = 294 + 196`.

### 6.4 Consistency rules

```text
put_object_count   == 3 * completed_requests + locator_put_attempts
locator_put_attempts in {0, 1, 2, 3}
head_object_count  == 0        (acquisition)
get_object_count   == 0        (acquisition)
list_operations    == 0
control_operations == 0
```

The accepted bound `head_object_count <= 3 * completed_requests + 1` is **replaced by equality
with zero**, which is stricter and needs no derivation from the completed-request count.

### 6.5 Partial and refused runs — accounted separately

**A refused run did not perform 145 operations, and must never be reported as though it had.**

| Outcome | Acquisition S3 operations |
|---|---|
| Halted at the *n*-th completed request, `PARTIAL` locator published | `3n + locator_put_attempts`, with `0 <= n < 48` and `locator_put_attempts` in `{1,2,3}` |
| Halted, no safe locator attempt — `LOCATOR_NOT_PUBLISHED` | `3n`, with `0 <= n < 48` |
| Bronze collision — BRONZE_NAME_OCCUPIED | the collided PutObject **is** an invocation and **is** counted; nothing after it in that publication step is |
| Locator refused — LOCATOR_NAME_OCCUPIED | `144 + locator_put_attempts` |

**Public counters report the real observed invocation count**, never a nominal one. That rule is
carried over from ADR-0018 §9.3 unchanged, and it is the reason the ranges above are ranges.

### 6.6 Superseded arithmetic

Upon acceptance, these ADR-0018 figures are **superseded for the acquisition actor** and survive
only as clearly labelled history: `145 to 290`, `147 to 292`, `294 to 584`, `485 to 780`, the
`zero to 145` conditional HeadObject range, and the per-run maximum of `292`. The assessment
figures `194` and `195 to 196` are **not** superseded.

---

## 7. Re-derived deadline and admission arithmetic

Re-derived from the obligations, not edited.

**Preserved exactly, and not reopened by this ADR:** the 1,800-second total elapsed acquisition
deadline; its measurement on an injected monotonic clock; its scope from the first provider
request to the terminal locator result; the 48-request maximum; the zero-provider-retry rule; the
SDK automatic-retry prohibition; the explicit bounded connect and read socket timeouts;
sequential execution; the minimum one-second pacing and the rule that pacing is refused rather
than shortened; Run A and Run B separation with its eight-day minimum; the assessment operation
envelope; the P1–P9 ceilings; the absence of any aggregate provider verdict; the absence of any
provider selection; and the open status of G1 and G2.

**The locator terminal reserve.** The permitted terminal sequence is now at most three locator
PutObject attempts and **zero** locator HeadObject, plus deterministic construction and terminal
classification:

```text
L  >=  3 * T_s3      three locator PutObject attempts
     + 0 * T_s3      zero locator HeadObject
     + C             deterministic construction and terminal classification
   =   3 * T_s3 + C
```

**The per-request downstream obligation.** One request's worst case is now **three** Bronze
PutObject and **zero** collision HeadObject:

```text
3 * T_s3
```

**Configuration feasibility — refused, never clamped:**

```text
T_s3 > 0
C    >= 0
L    >= 3 * T_s3 + C
L    <  D
T_req + P + 3 * T_s3 + L  <=  D
```

**Per-request admission, checked before every provider request:**

```text
remaining >= T_req + 3 * T_s3 + L
```

**The uncomfortable consequence, restated with the new numbers.** At the compiled worst case
`48 * (30 + 1) = 1488 s`, leaving **312 seconds** for at most 144 Bronze PutObject and at most
three locator PutObject — 147 operations, about **2.12 seconds per S3 operation**, against
roughly **1.08** under the accepted design's 292. The allowance roughly doubles because the
operation count roughly halves. **It is still not a completion guarantee.** The 1,800-second
deadline stays a safety bound on elapsed time: a slow provider means the run halts short,
publishes a `PARTIAL` locator, and the assessor refuses to evaluate it.

**The ceiling is not raised.** Lowering it remains a configuration choice; raising it remains an
ADR change.

---

## 8. The alternative this ADR rejects

**The application-only alternative is not adopted.** It would grant the acquisition role
s3:GetObject and rely solely on the program exposing no get_object method.

- A **compromised credential-holding acquisition process could read known licensed objects**, and
  it knows every key it writes.
- That **would invalidate ADR-0018 §10.3's identity-system compromise argument**, which is the
  stated reason there are two roles rather than one.
- **Application API shape is valuable defense in depth and is not a substitute for IAM least
  privilege.** This ADR keeps that layer; it declines to make it the only layer.
- **A small implementation size is not sufficient justification for weakening the accepted
  security boundary.** The application-only option is by far the smaller change, and that is not
  an argument.

**The weaker alternative was never authorized**, and nothing here should be read as retracting a
permission that was never granted. It was one option among several in a read-only feasibility
review, and it is declined.

---

## 9. Exactly what this would amend

Upon acceptance, and not before:

| ADR-0018 clause | Amendment |
|---|---|
| **§10.1** | acquisition role receives no s3:GetObject, no s3:GetObjectVersion and no s3:GetObjectAttributes; performs no HeadObject; the metadata-only collision resolution is removed from its grant |
| **§7.4** | `LOCATOR_COLLISION` becomes LOCATOR_NAME_OCCUPIED, without the different-content claim; BRONZE_NAME_OCCUPIED is added |
| **§9.1** | conditional HeadObject `zero to 145` becomes **zero**; total S3 operations `145 to 290` becomes **145 to 147** |
| **§9.2** | the retry permission is retained unchanged; its 412 landing now fails closed instead of resolving to already-present |
| **§9.3** | maximum totals `147 to 292` become **145 to 147**; the consistency bound on HeadObject becomes equality with zero |
| **§9.5** | the acquisition rows and the whole-package envelope `485 to 780` become **485 to 490** |
| **§4.5.3** | `L >= 4 * T_s3 + C` becomes `L >= 3 * T_s3 + C`; both `6 * T_s3` terms become `3 * T_s3` |

**Everything else in ADR-0018 is untouched**, including the eight private subject classes, the
three datasets, the page limits, the 48-request inventory, the two-run separation, the locator
schema and size ceiling, the two-role split, the parser, evaluator and report boundaries, the
deletion-runbook clarification, and every P1–P9 ceiling.

---

## 10. Chronology, preserved

Recorded so that no reader concludes the corrected design was always there:

1. **ADR-0018 was accepted** with metadata-only collision resolution **and** an IAM-level
   prohibition on acquisition object-byte reads. Both were accepted in good faith, and the
   conflict between them was not apparent from the design alone.
2. **The offline implementation merged dormant** — PR #41, then the fixed-count correction in
   PR #44 — and was never executed.
3. **A later read-only infrastructure-feasibility reconciliation established** that AWS maps
   HeadObject to s3:GetObject and publishes no independent metadata action.
4. **That made the two accepted requirements jointly undeployable**, which is what
   STOPPED_ARCHITECTURE_GAP_HEAD_REQUIRES_GET records.
5. **ADR-0019 now proposes** removing acquisition-side metadata reads while preserving IAM least
   privilege.
6. **No infrastructure was built and no run occurred before the discovery** — infrastructure
   deployment was never authorized, no qualification IAM role was ever created, and Run A, Run B
   and the combined assessment have never run. The defect was found before it could cost
   anything.
7. **ADR-0017 remains unchanged** throughout.

**ADR-0018 is not rewritten as though the corrected design had always existed.** Its accepted text
stands, and this ADR names the clauses it would amend rather than editing them in place.

---

## 11. Consequences

**Accepted, if this ADR is accepted.** The acquisition role becomes genuinely write-only at both
layers, and the compromise argument that justifies the two-role split becomes true of the
identity system rather than only of the code. Acquisition S3 operations roughly halve, and the
deadline's per-operation allowance roughly doubles.

**Paid for, if this ADR is accepted.** Idempotent re-publication is no longer distinguishable
from a genuine collision; a locator retry whose earlier attempt committed now fails closed as a
false negative; and any occupied name — however benign — halts a run and requires a new execution
identity under a separate authorization.

**Not resolved by this ADR.** G1 stays **OPEN** and G2 stays **OPEN**; no provider is selected;
Phase 3 stays **NOT COMPLETE**; CONTROL publication stays **DEFERRED**; live trading stays
**HARD-DISABLED**; a third ADR-0017 authenticated attempt stays **NOT AUTHORIZED**; and full
P1–P9 empirical qualification stays separate and unexecuted.

**Still required after acceptance, each separately authorized:** an implementation correction
introducing the write-only publication surface, an infrastructure design review, a Terraform and
IAM implementation, an infrastructure mutation, Run A, Run B and the combined assessment.
**ADR-0019 opens none of them.**
