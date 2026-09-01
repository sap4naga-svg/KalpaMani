# ADR-0020 — Request-scoped immutable payload identity for private empirical qualification

**Status: PROPOSED — no authority until the pull request introducing it is independently
reviewed and merged.**

While that pull request is open this ADR governs nothing. It is a proposal to amend one identity
rule inside [ADR-0018](ADR-0018-bounded-private-empirical-sharadar-qualification.md) as amended by
[ADR-0019](ADR-0019-write-only-acquisition-collision-policy.md), and until it merges **ADR-0018 as
amended by ADR-0019 is what governs**. That is the same conditional treatment ADR-0017, ADR-0018
and ADR-0019 were each given, and it is written down rather than assumed.

**The condition above has since been satisfied.** **PR #49 merged** — merge commit
**`e4d328af53f2663c570f94e6c090c3296db8cb9d`**, approved ADR head
**`d9bbb17b7f174c34223eb4736d763f115daf229f`** — after an **independent review**. So
**ADR-0020's conditional effectiveness event has occurred** and this ADR is now
**ACCEPTED / IN FORCE**, as **architecture only**. The status line above is the conditional
text this ADR was written with; it is **preserved as history, not rewritten**, and **while
PR #49 was open, ADR-0020 was proposed and carried no authority** — which was true then and
stays true. **The merge approved architecture only, and authorized no implementation, no
infrastructure mutation, no deployment and no execution.** **PR #48 must be corrected against
ADR-0020 before it may be independently reviewed or merged** — see §9.

**Date:** 2026-09-01
**Supersedes:** nothing wholesale. **Amends, upon acceptance:** the qualification **payload
object key derivation** of ADR-0018, and nothing else.
**Does not amend:** ADR-0019, ADR-0017, ADR-0016, ADR-0015, ADR-0014, ADR-0013, ADR-0012,
ADR-0011, ADR-0010, ADR-0009, ADR-0008, ADR-0007, ADR-0006 or ADR-0005.

---

## 1. What is unchanged by proposing this

**This ADR authorizes nothing.** It carries **no implementation authority** and **no
infrastructure authority**; it **authorizes no deployment**; and it **authorizes no Run A, no
Run B and no combined assessment**. No production-code correction, no Terraform, no IAM, no
infrastructure mutation, no provider request, no S3 operation, no credential retrieval and no
execution of any kind follows from accepting it. Implementation, infrastructure mutation and
execution stay three separate gates and are never collapsed into one.

**This ADR does not make PR #48 mergeable**, and **it does not retroactively change the status of
PR #48**. PR #48 is **open, unmerged and blocked on architecture**, it was **left untouched by
this proposal**, and it stays that way until this ADR is independently reviewed, merged and
synchronized and PR #48 is corrected against it under a separate authorization.

**It supersedes only the qualification payload-key identity rule** necessary to resolve legitimate
duplicate payload bytes. Every other identity in the package — the acquisition claim key, the
acquisition record key, the locator key and the private report key — is untouched.

**It does not supersede ADR-0019's write-only collision policy.** Acquisition stays conditional
`PutObject` only, with zero `HeadObject`, zero `GetObject` and a fail-closed 412.

**It does not supersede ADR-0017.** Its entry point, its composition root, its three-`PutObject`
accounting and its use of the shared research object store are untouched.

**It does not modify the shared general-purpose Bronze or `S3ResearchObjectStore` contract.**
`bronze_payload_key`, `acquisition_claim_key`, `bronze_acquisition_key` and the shared store keep
the behaviour they were accepted with.

**ADR-0018 remains ACCEPTED / IN FORCE except as amended by ADR-0019 and, upon acceptance, by
this ADR. ADR-0019 remains ACCEPTED / IN FORCE.** **Infrastructure remains blocked.** Accepting a
corrected identity is not permission to build it.

---

## 2. Context — what PR #48 exposed

PR #48 implements ADR-0019's fail-closed write-only collision rule offline. **PR #48 is not
defective for obeying ADR-0019.** It obeyed the accepted rule exactly, and in doing so it made
visible a **pre-existing incompatibility in the accepted architecture** between two clauses that
were each accepted separately:

| Accepted clause | Source |
|---|---|
| a complete acquisition run is **exactly 48 requests** and **exactly 144 Bronze `PutObject`** | ADR-0018 §9, and the assessor's fixed-count admission |
| the qualification payload object is **content-addressed**, keyed by `(provider, dataset, digest)` | ADR-0018, inherited from the general-purpose Bronze namespace |
| an acquisition-side **412 fails closed** with no read, no `HeadObject`, no comparison and no adoption | ADR-0019 §4.2, §6.5, §11 |

ADR-0019 §6.1 states that *a successful complete run has no collision, by construction*. That
holds only if no two of a run's 144 Bronze writes can legitimately derive the same name. **Under
the current payload-key derivation, two of them can.**

**The legitimate duplicate-payload collision** is the name this ADR gives that conflict, and
two byte-equality cases are legitimate rather than pathological:

1. **Header-only completeness probes.** ADR-0018's page two exists to prove page one was complete.
   A complete page one legitimately yields an **empty second page** — a header-only body that is
   **byte-identical for every subject in the same dataset**. Eight subjects produce up to eight
   identical page-two bodies per dataset.
2. **An unchanged snapshot re-observed in Run B.** ADR-0018 requires two runs at least eight
   calendar days apart. A `tickers` snapshot that did not change in those eight days returns
   **byte-identical bytes**, which Run A already published.

Under the current derivation the second such write lands on an occupied name, ADR-0019 correctly
fails it closed, and the run halts. **The accepted complete-run shape is therefore unreachable
whenever a legitimate duplicate payload occurs**, and no amount of correctness in the publication
code can change that: the defect is in the **name**, not in the write.

**This is an identity and key-contract problem. It is not a reason to weaken write-only
acquisition.** The alternative — letting acquisition read or compare the occupied object — is
exactly what ADR-0019 removed, for the IAM reason ADR-0019 §3 records: AWS authorizes `HeadObject`
with `s3:GetObject` and exposes no independent metadata action, so a role that may resolve a
collision is a role that may read every key it can name.

**The conflict exists before any AWS deployment**, and is demonstrable from committed code with
synthetic bytes alone. No real payload, no provider request, no S3 operation and no private
evidence is needed to prove it, and none was used.

---

## 3. The exact current derivation, and where it collides

The three durable artifacts of one completed request derive their names as follows on merged
`main`:

| Artifact | Current key | Scoped by |
|---|---|---|
| claim | `licensed/bronze/_acquisition_claims/<payload-digest>/<acquisition-id>.json` | digest **and acquisition identity** |
| payload | `licensed/bronze/<provider>/<dataset>/objects/sha256/<payload-digest>` | **digest only**, within provider and dataset |
| record | `licensed/bronze/<provider>/<dataset>/acquisitions/<payload-digest>/<acquisition-id>.json` | digest **and acquisition identity** |

The acquisition identity is `acquisition_id(execution_id, request)` — the form
`<execution>.<24 hex>`, whose digest binds the execution, the provider, the dataset, the subject,
the requested range, the response format and both page values. It is carried into Bronze as
`RetrievalMetadata.ingestion_run_id`.

**So the claim and the record are already execution-and-request-scoped, and the payload is not.**
Two different governed request observations differ in their acquisition identity even when their
bytes are equal, so their claim and record names differ; their payload name is a pure function of
`(provider, dataset, digest)` and is therefore **identical**. The same holds across executions:
Run A and Run B differ in execution identity, so their claims and records differ, and an unchanged
payload lands on **one** name.

**The scope of this ADR is therefore exactly one key class.** The claim and record keys need no
change, and this ADR proposes none for them.

---

## 4. Decision

**ADR-0018 qualification payload objects use an execution-and-request-scoped immutable key that
also binds the SHA-256 payload digest.**

### 4.1 The canonical identity

The qualification payload identity is derived from exactly three non-secret inputs:

```text
execution_identity        the accepted run identity already bound by the
                          locator and by the acquisition record
request_ordinal           the deterministic ordinal of this request within the
                          locked 48-request inventory
payload_sha256_digest     the SHA-256 of the exact stored payload bytes
```

An equivalent canonical encoding is permitted, and **all three bindings must be preserved**.

The key is structurally:

```text
<qualification-payload-prefix>/
  <execution-identity>/
  requests/
  <zero-padded-request-ordinal>/
  sha256/
  <payload-digest>
```

**Reconciled with the repository's existing naming conventions**, the qualification payload prefix
is `bronze/<provider>/<dataset>/qualification`, so a complete key reads:

```text
licensed/bronze/<provider>/<dataset>/qualification/<execution-identity>/requests/<NN>/sha256/<payload-digest>
```

Each element of that choice answers an existing rule rather than a preference:

| | |
|---|---|
| **stays under `bronze/`** | the deletion runbook already deletes `bronze/` by prefix, so the new namespace is covered with **no runbook change** and no new deletion step |
| **keeps `<provider>/<dataset>`** | the accepted reason payload storage is not globally de-duplicated: a termination obligation arriving for one vendor must not have to destroy another vendor's evidence |
| **`qualification` and `requests` are ordinary segments** | no leading underscore, so neither can collide with the reserved `_acquisition_claims` namespace, which the existing segment grammar refuses to any provider |
| **`sha256/<digest>` stays the tail** | the digest remains the **last** path segment, exactly as the general-purpose namespace spells it |
| **ordinal zero-padded to two digits** | `00`–`47` covers the locked inventory, and zero padding keeps lexical order and numeric order identical |
| **every segment passes the existing path-segment grammar** | no new grammar, no new classification, and `LICENSED` remains the only classification this key can carry |

Requirements the derivation must satisfy:

* `execution_identity` is the **accepted run identity** already bound by the locator's
  `execution_id` and by each acquisition record.
* `request_ordinal` is the **deterministic ordinal from the locked 48-request inventory** — the
  index of the request in the plan's canonical order, which is dataset order, then subject
  lexicographically, then page offset ascending.
* The ordinal is **bound to the plan and request inventory and cannot be supplied freely by the
  provider**. It is a function of the locked plan alone; nothing in a provider response, header,
  status or body can select, shift or influence it.
* `payload_sha256_digest` is computed from the **exact stored payload bytes**.
* The digest **remains present in durable evidence independently of the key** — the acquisition
  record's `content_sha256` and the locator entry's `payload_sha256` are unchanged.
* The key contains **no provider subject, ticker, date range, API path, credential, bucket,
  account, owner name or other private request value**.
* The same execution, request ordinal and payload bytes **deterministically produce the same
  key**.
* A **different execution identity produces a different key**.
* A **different request ordinal produces a different key**.
* **Different payload bytes produce a different digest and a different key.**
* **Identical bytes from different requests, or from different runs, no longer collide.**
* A **retry of the same publication attempt targets the same key** — there is **no random
  suffix**, no timestamp, no attempt counter and nothing else that changes between attempts of
  one publication.
* An **occupied name at that exact key still fails closed** under ADR-0019.

**No list operation and no preflight existence check is introduced.** The key is derived, not
discovered.

### 4.2 Integrity requirements

The key is an addressing scheme. **It is not integrity proof, and it must never be treated as
one.** Before accepting payload evidence, assessment must validate **all** of the following:

1. The acquisition record's **execution identity matches** the accepted locator and run.
2. The **request ordinal is within the locked request inventory** — `00` through `47`.
3. The ordinal **maps to the request evidence being assessed** — the same dataset, subject, page
   limit and page offset the locator entry records.
4. The acquisition record's **stored payload digest has the accepted canonical form** — lowercase
   hexadecimal, exactly 64 characters.
5. The **expected qualification payload key is deterministically reconstructed** from the
   execution identity, the request ordinal and the payload digest.
6. The **recorded payload key exactly equals the reconstructed key**.
7. The payload is **read only by the separately authorized assessment role and process**.
8. **SHA-256 is recomputed over the retrieved payload bytes.**
9. The **recomputed digest exactly equals the durable digest**.
10. **Any mismatch fails closed before parsing or evaluation.**

This is defense in depth, and each layer is load-bearing:

```text
locator / run binding
  + request-inventory binding
  + canonical-key binding
  + record binding
  + payload-byte digest verification
```

**Do not treat the key name alone as integrity proof.** A name states where bytes were put; only
the recomputed digest states what they are.

### 4.3 Write-only acquisition is preserved, exactly

ADR-0019 is preserved **unchanged**:

* Acquisition performs **conditional `PutObject` only**.
* Acquisition performs **no `HeadObject`**.
* Acquisition performs **no `GetObject`**.
* Acquisition performs **no `GetObjectAttributes`**.
* Acquisition performs **no S3 listing**.
* A **412 means only that the name was occupied**.
* A **412 establishes neither identical nor different content.**
* **No compare, adopt, resume or deduplicate behaviour exists.**
* A Bronze 412 remains **`BRONZE_NAME_OCCUPIED`**.
* A locator 412 remains **`LOCATOR_NAME_OCCUPIED`**.
* An **ambiguous write followed by a 412 remains a safe-direction false negative**: the run
  refuses rather than assuming its earlier attempt committed.
* **No occupied object is counted as retained or verified evidence.**

**The new identity reduces legitimate cross-request collisions. It does not relax collision
handling.** After this amendment a Bronze payload collision means something narrower and more
serious than it did before — the same execution, the same ordinal and the same bytes were
published twice — and it still fails closed.

### 4.4 ADR-0017 and shared-store isolation

A later, separately authorized implementation gate must introduce a **qualification-specific
payload-key builder**. That implementation must:

* be **confined to the ADR-0018 / ADR-0019 / ADR-0020 qualification code**;
* **not change the shared general-purpose `bronze_payload_key`**;
* **not change `S3ResearchObjectStore`**;
* **not change ADR-0017 publication behaviour**;
* **not make ADR-0017 depend on execution- or request-scoped qualification keys**;
* remain **structurally unreachable from ADR-0017**;
* **avoid copying unrelated shared publication logic** — take what it needs from the module that
  owns it, and restate nothing it can import.

**If the later implementation cannot preserve this separation, it must stop for a new architecture
decision** rather than widening the shared contract to fit.

### 4.5 Durable-schema impact

* **No new locator field is introduced.**
* **No private subject value is introduced.**
* **No additional S3 read is introduced.**
* **No S3 list is introduced.**
* **No provider request is introduced.**
* The acquisition record **continues to carry the exact payload key and digest**.
* **The permitted value pattern of the qualification payload-key field changes** — the same field,
  holding a key of the new shape.
* **Any validator that reconstructs the old general-purpose payload key must later be corrected to
  reconstruct the qualification-specific key.** That correction belongs to the implementation gate,
  not to this ADR.
* **Old dormant candidate evidence does not exist**, and **no migration is authorized or needed**.
* **No already-published private evidence is being renamed, copied, deleted or read.**

**The merged durable record already carries enough to reconstruct the new key, so no new field is
required**, and this is checked rather than assumed:

| Input | Where it already lives |
|---|---|
| execution identity | the locator's top-level `execution_id`, and the `<execution>` half of each entry's `acquisition_id` |
| request ordinal | derivable from the locator's own entries — each carries `dataset`, `subject`, `page_limit` and `page_skip`, which is precisely the request-coordinate tuple the assessor already builds and orders canonically |
| payload digest | the locator entry's `payload_sha256`, and the acquisition record's `content_sha256` |

### 4.6 Operation and deadline arithmetic

**The accepted ADR-0019 arithmetic is preserved. The new key identity introduces no additional
operation.**

```text
Successful acquisition:
  Bronze PutObject:       exactly 144
  Locator PutObject:      1 to 3
  Total PutObject:        145 to 147
  HeadObject:             exactly 0
  GetObject:              exactly 0
  Total acquisition S3:   145 to 147
Two successful runs:
  290 to 294
Assessment:
  194 GetObject
  1 report PutObject
  0 to 1 conditional HeadObject
  195 to 196 total
Whole successful package:
  485 to 490
```

The deadline arithmetic is preserved unchanged:

```text
D = 1800 seconds
L >= 3 * T_s3 + C
per-request S3 obligation = 3 * T_s3
T_req + P + 3 * T_s3 + L <= D
remaining >= T_req + 3 * T_s3 + L
```

Deriving a key is local, deterministic computation. It sends nothing, reads nothing and waits for
nothing, so it adds no S3 operation, no provider request and no term to the deadline.

### 4.7 Scenarios

| Scenario | Required result |
|---|---|
| Two different request ordinals return identical bytes | **Different keys**; both may publish |
| Run A and Run B return identical bytes | **Different keys**, because the execution identities differ |
| Same request publication retried after an ambiguous transport failure | **The same key** |
| That retry receives a 412 | **Fail closed** — `BRONZE_NAME_OCCUPIED` |
| Different bytes for the same execution and ordinal | **Different digest and different key**; only the single governed observation is publishable — see below |
| Recorded key does not match the reconstructed key | **Assessment refuses** |
| Retrieved bytes do not match the recorded digest | **Assessment refuses, before parsing** |
| Occupied key contains benign identical bytes | **Still fails closed**; acquisition does not read it |
| Occupied key contains hostile bytes | **The same sanitized fail-closed behaviour**, and nothing about the occupying content is stated |
| Request subject values differ | **No subject value appears in either key** |

**The same-execution, same-ordinal, different-bytes case, exactly.** One governed request has
**one** observation. ADR-0018 permits **no provider retry** (`max_attempts = 1`, arithmetically
forced) and **no resume**: a second execution reads a new retrieval instant, derives a different
acquisition identity and is a different execution. So within one execution a given ordinal is
requested **once**, and the bytes it returned are that observation.

Two different payloads for one execution and one ordinal could therefore only arise from a second
attempt that the architecture does not permit, or from an object of unknown provenance already
sitting at a name this run derives. **The architecture must not permit two competing payloads for
one governed request to be accepted as a complete observation.** The digest is in the key, so a
second, different payload would be written to a **different** name — and it would then be a second
object that no acquisition record and no locator entry references. **The acquisition record and
the locator bind only the single governed terminal outcome**: exactly one payload key, one digest
and one byte count per ordinal, so an unreferenced object is not evidence, is never read, is never
assessed, and is covered by prefix-based deletion like everything else under `bronze/`.

---

## 5. Alternatives considered and rejected

| Alternative | Why it is rejected |
|---|---|
| **Let acquisition resolve the collision** — `HeadObject` the occupied name and continue if the content matches | This is exactly what ADR-0019 removed. AWS authorizes `HeadObject` with `s3:GetObject`, so restoring it restores object-read authority to a process that derives every key it writes |
| **Treat a Bronze 412 as idempotent success** | A 412 does not establish that the occupied object is identical. Accepting it would let an object of unknown provenance be counted as this run's evidence |
| **Salt the key with a random or timestamped suffix** | A retry of the same publication would then target a **new** name, so an ambiguous commit could silently produce two objects for one observation, and no assessor could reconstruct the key deterministically |
| **Scope the payload key by execution only** | Insufficient: the header-only completeness probes collide **within** one execution |
| **Scope the payload key by ordinal only** | Insufficient: an unchanged Run B observation collides with Run A at the same ordinal |
| **Drop the digest from the key** | The digest in the last segment is what makes the name self-describing and what makes a different-bytes write land somewhere else instead of overwriting. It also keeps the reconstruction check in §4.2 meaningful |
| **Change the shared general-purpose `bronze_payload_key`** | Production ingestion is not qualification. Global content addressing is the right default for backfill and update, where identical bytes genuinely are one object; widening this change to the shared contract would impose per-request storage on a path that never asked for it |
| **Relax the assessor's fixed 48-request admission** | The fixed count is what makes a pair assessable at all, and PR #44 exists precisely because an earlier version admitted a self-consistent pair at some other count |

---

## 6. Consequences and trade-offs

**Advantages**

* **Legitimate identical payloads across requests no longer collide.**
* **Unchanged Run B observations remain publishable**, so the two-run design survives contact with
  a provider whose snapshot did not move in eight days.
* **Write-only least privilege is preserved** — the acquisition role still receives no object-read
  action.
* **Digest verification remains end to end**, from the bytes the provider returned to the bytes
  the assessor parses.
* **Operation ceilings remain unchanged** at 145–147, 290–294, 195–196 and 485–490.
* **No deduplication read is needed** — nothing has to look before it writes.
* **Request evidence remains independently retainable**: each of the 48 observations has its own
  object, so one request's evidence is never silently represented by another's.

**Costs, stated rather than absorbed**

* **Qualification payloads are no longer globally deduplicated by payload digest.**
* **Identical bytes may be stored more than once** — up to once per request per run.
* **Qualification-specific addressing diverges intentionally from the shared general-purpose Bronze
  payload key**, and that divergence is a thing a reader must now know.
* **Assessment must reconstruct and validate the qualification-specific key**, which is one more
  rule the assessor carries.
* **PR #48 requires a later code correction before review or merge.**
* **Same-attempt ambiguous-commit retries can still fail safely on a 412.** This amendment does not
  remove that false negative, and does not try to.

**Why the additional storage is acceptable here, and only here.** The package is bounded by
construction:

```text
two runs
48 requests per run
one payload object per request
maximum 96 qualification payload objects
```

Ninety-six objects, each bounded at 4 MiB by the accepted response ceiling, is a storage cost that
does not need an optimisation. **Do not generalize this choice to ingestion or CONTROL storage.**
Production backfill and update operate at a scale where global content addressing earns its
keep, and they are a different acquisition mode under a different, unauthorized gate.

---

## 7. What accepting this would and would not do

**Would:** make the request-scoped payload identity the governing architecture for ADR-0018
qualification payload objects.

**Would not:** authorize an implementation, authorize infrastructure, authorize a deployment,
authorize Run A, authorize Run B, authorize the combined assessment, make PR #48 mergeable, change
PR #48's status retroactively, select a provider, close G1, close G2, complete Phase 3, authorize
CONTROL publication, or enable live trading — which remains **HARD-DISABLED**.

**G1 OPEN · G2 OPEN · G3 CLOSED · G4–G7 OPEN**, ADR-0005 **PROPOSED**, INC-0002 **OPEN**, no
provider selected, Phase 3 **NOT COMPLETE**, CONTROL publication **DEFERRED**, and a **third
ADR-0017 authenticated attempt NOT AUTHORIZED**.

---

## 8. The state of PR #48

**PR #48 is OPEN, non-draft, UNMERGED, BLOCKED ON ARCHITECTURE, and untouched by this proposal.**
It was not edited, rebased, amended, reviewed, commented on, retitled, closed or merged, and
auto-merge was not enabled on it. It was inspected read-only, to confirm the conflict recorded in
§2.

**PR #48 correctly implemented ADR-0019.** It is blocked because the architecture it correctly
implemented contains the incompatibility this ADR proposes to resolve — not because its
implementation is wrong.

**PR #48 cannot be reviewed or merged until this ADR is independently reviewed, merged and
synchronized, and PR #48 is corrected against it.** That correction is a separate gate and is
**NOT BEGUN**.

---

## 9. Post-merge status — recorded after this decision

**This section is a historical note added after the decision above, and it changes nothing this
ADR decided.** §1–§8 record the amendment as it was proposed and reviewed; that record stands
unedited. What follows is what happened afterwards.

**ADR-0020 architecture: ACCEPTED / IN FORCE.** **PR #49 merged**, merge commit
**`e4d328af53f2663c570f94e6c090c3296db8cb9d`**, approved ADR head
**`d9bbb17b7f174c34223eb4736d763f115daf229f`**, after an **independent review**. **ADR-0020's
conditional effectiveness event has occurred.** **While PR #49 was open, ADR-0020 was proposed
and carried no authority**, and **ADR-0018 as amended by ADR-0019 governed the qualification payload
identity before the PR #49 merge** — historical facts that stay true and are not rewritten as
though this ADR had always been effective.

**The merge approved architecture only, and authorized no implementation, no infrastructure
mutation, no deployment and no execution.** The request-scoped payload identity is now the
governing architecture for ADR-0018 qualification payload objects, and **ADR-0020's amendment is
now authoritative architecture**. **ADR-0020 supersedes no ADR wholesale**; it amends only the
qualification payload-key identity rule. **ADR-0019 remains ACCEPTED / IN FORCE**, **ADR-0018
remains ACCEPTED / IN FORCE except as amended by ADR-0019 and by this ADR**, **ADR-0017 is not
amended or superseded**, **ADR-0011 is not amended or superseded**, and **the shared
S3ResearchObjectStore remains unchanged**.

**The implementation gap is open, and it is not concealed by the architecture being accepted.**

| Layer | Current status |
|---|---|
| Architecture | **ADR-0020 accepted and effective** |
| Existing code | **merged, dormant, not yet conforming** |
| Corrective code | **not authorized, not implemented** |
| Terraform / IAM | **not authorized, not implemented** |
| Deployment | **not authorized, not performed** |
| Execution | **ZERO** |

**No qualification payload-key builder exists.** **ADR-0020 implementation: NOT AUTHORIZED / NOT
IMPLEMENTED.** **The ADR-0018 offline implementation remains MERGED / DORMANT**, it still derives
the qualification payload name from the shared content-addressed builder, and **the current dormant
implementation is therefore not deployable under the authoritative architecture**. **No claim is
made that the request-scoped payload identity is already implemented**, and **no claim is made
that the qualification payload-key builder already exists** — it does not. **Infrastructure
design: BLOCKED pending implementation correction.**

**PR #48 is still OPEN, non-draft, UNMERGED and untouched.** It was not edited, rebased, amended,
reviewed, commented on, retitled, closed or merged by this decision or by its merge, and
auto-merge was not enabled on it. **PR #48 correction against ADR-0020: NOT BEGUN**, and
**PR #48 ready for review or merge: NO**. **PR #48 is not defective for obeying ADR-0019** — its
implementation work exposed the architectural identity gap this ADR resolves, and it now
**requires a separate correction against the accepted ADR-0020 design**. **The next separately
authorized implementation gate is correcting PR #48 against ADR-0020**, and **infrastructure
remains blocked until that correction is implemented, independently reviewed and merged.**

**Acceptance of ADR-0020 is not authorization to implement or execute it.** Run A, Run B, the
combined assessment, Terraform, IAM, infrastructure mutation and deployment each remain
**NOT AUTHORIZED**; **G1 and G2 stay OPEN**; no provider is selected; Phase 3 stays **NOT
COMPLETE**; CONTROL stays **DEFERRED**; live trading stays **HARD-DISABLED**; and a third ADR-0017
authenticated attempt stays **NOT AUTHORIZED**.
