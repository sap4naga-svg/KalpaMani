# ADR-0022 — Qualification permission-set name limit

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0022 is proposed and carries no
authority. That is a statement about the present, it will remain true of these days after any
later merge, and it is not to be rewritten as though this decision had authority before it was
accepted.

**This decision corrects one accepted architecture value and nothing else.** It implements
nothing, creates nothing, inspects nothing, binds nothing, deploys nothing, plans nothing and
runs nothing. No AWS identity, account, profile, credential, cache, permission set, assignment,
role, trust policy or policy attachment was read, created, modified or verified in producing it,
and none may be read, created, modified or verified by accepting it. **No Terraform command and
no AWS CLI or SDK call was run**, and the provider constraint below was established from the
pinned provider's public source and official documentation alone.

---

## 1. Context

[ADR-0021](ADR-0021-qualification-runtime-principal-and-trust-model.md) chose the qualification
runtime principal and trust model: IAM Identity Center permission-set roles, two permission sets,
two named profiles, one governed operator group. It is **ACCEPTED / IN FORCE** as architecture
only, and it named the acquisition permission set **`KalpaManiQualificationAcquisition`**.

PR #56 implemented that architecture offline, and **implemented it faithfully**: it declared the
acquisition permission set under exactly the name ADR-0021 accepted. **PR #56 is not defective
for implementing the accepted architecture as written.**

**Independent review of PR #56 found that the accepted name cannot be created by the pinned
Terraform provider.** The name is 33 characters; the provider's `aws_ssoadmin_permission_set`
`name` attribute is validated to 1–32 characters. The defect is therefore **in the accepted
architecture, not in the implementation**, and correcting only PR #56 would leave the
implementation contradicting the decision that governs it. **The independent review correctly
refused the merge**, and the correction belongs in an ADR.

### 1.1 What this decision does not reopen

ADR-0021's identity contract — the exact-account binding, the STS assumed-role parsing, the
role-name prefix verification, the AWS-generated suffix grammar and the structure-not-provenance
limitation — was **independently approved during the PR #56 review**. **ADR-0022 does not reopen
the suffix grammar**, and it changes no part of that contract.

---

## 2. The confirmed defect

**Reproduced mechanically, from merged artifacts and the pinned provider contract.** No Terraform
was initialized, validated, planned or applied, and no provider binary was downloaded or executed.

### 2.1 The exact lengths

| Name | Length | Within 1–32 | Allowed characters | Provider verdict |
|---|---|---|---|---|
| `KalpaManiQualificationAcquisition` — ADR-0021's accepted acquisition name | **33** | **no** | yes | **refused, on length** |
| `KalpaManiQualificationAssessment` — the accepted assessment name | **32** | yes | yes | accepted |
| `KalpaManiQualificationAcquire` — this ADR's proposed acquisition name | **29** | yes | yes | accepted |

**All three names satisfy the provider's allowed-character grammar.** The old acquisition name
fails on **length alone**, by exactly one character.

### 2.2 The pinned provider and its validator

The research data plane pins **`hashicorp/aws` v6.62.0** in its tracked lock file, under a
`~> 6.0` constraint. At tag `v6.62.0`, the `aws_ssoadmin_permission_set` resource declares:

```go
names.AttrName: {
	Type:     schema.TypeString,
	Required: true,
	ForceNew: true,
	ValidateFunc: validation.All(
		validation.StringLenBetween(1, 32),
		validation.StringMatch(regexache.MustCompile(`[\w+=,.@-]+`), "must match [\\w+=,.@-]"),
	),
},
```

`validation.StringLenBetween(1, 32)` permits **1 to 32 characters inclusive**. A 33-character name
is refused by the provider itself, at plan time, before any AWS call is made. The constraint is
not a provider invention: the AWS `CreatePermissionSet` API documents the same **minimum length
of 1, maximum length of 32** and the same pattern `[\w+=,.@-]+`.

The attribute is also **`ForceNew`**, which is why the name is worth getting right before anything
is created rather than after: changing it later replaces the resource.

### 2.3 Why the existing offline guards did not catch it

**PR #56's offline parser and tests did not independently enforce the provider's 32-character
maximum.** Its Terraform declares both names as locals, its documentation-audit constant and its
verifier constant each carry the 33-character string, and its tests assert that the two
permission-set names are distinct and correctly wired — but **no guard anywhere in PR #56
measures a permission-set name against 1–32 characters**. The only `32` in its changed files
belongs to the unrelated generated-suffix grammar.

Formatting and custom HCL parsing were insufficient for a structural reason rather than an
accidental one: **a formatter checks layout, and a repository-owned HCL parser checks the shapes
that repository chose to model.** Neither evaluates a provider's `ValidateFunc`, because neither
loads the provider. Only a real `terraform validate` against the pinned provider — which remains
unauthorized and unrun — or an explicit repository-side length guard can refuse a 33-character
name offline. **This ADR requires the second, and does not substitute it for the first.**

---

## 3. Decision

**Retire `KalpaManiQualificationAcquisition` as the acquisition permission-set name, and replace
it with `KalpaManiQualificationAcquire`.**

The replacement is **exactly 29 characters**, and that length is to be confirmed mechanically from
the string itself rather than transcribed.

**Unchanged by this decision:**

| Contract | Value |
|---|---|
| assessment permission-set name | `KalpaManiQualificationAssessment` |
| acquisition profile | `kalpamani-qualification-acquisition` |
| assessment profile | `kalpamani-qualification-assessment` |

**If ADR-0022 is accepted, the acquisition generated-role prefix becomes**
`AWSReservedSSO_KalpaManiQualificationAcquire_`. **That prefix is not effective while ADR-0022
remains proposed**, and the currently accepted prefix stays ADR-0021's until this decision is
independently reviewed and merged.

### 3.1 Why this name

- **29 characters**, comfortably inside the provider's 1–32 constraint.
- **Allowed characters only** — alphanumeric, matching `[\w+=,.@-]+`.
- **Preserves the `KalpaManiQualification` namespace**, so the two actors still sort and read
  together and the prefix stays unambiguous.
- **Preserves the acquisition meaning** through `Acquire`, which is the same verb the acquisition
  actor is named for throughout ADR-0018, ADR-0019 and ADR-0020.
- **Leaves three characters of provider-name headroom**, so a later related name is not forced
  against the ceiling again.
- **Requires no profile-name change** — a profile name is a local routing label and is not
  constrained by the permission-set validator.
- **Requires no actor-model change** — the same two actors, the same separation, the same
  permission sets, the same group assignment.
- **Requires no durable-schema change** — no locator field, no report field, no object key and no
  stored record mentions a permission-set name.
- **Requires no live migration, because nothing has been applied.** No permission set exists, no
  assignment exists, no role exists and no attachment exists, so there is nothing to rename,
  replace or delete.

### 3.2 Generated-role length, stated exactly

The generated role is named `AWSReservedSSO_<permission-set-name>_<suffix>`. **The IAM role-name
limit of 64 characters is a published, non-adjustable AWS limit.** The length of the AWS-generated
suffix is **not published**: suffix lengths seen in AWS documentation examples are
**example-based observations, not a documented guarantee**, and this ADR **does not encode any
fixed suffix length as an architectural guarantee**. What it does record is the direction of the
margin: `AWSReservedSSO_` plus a 29-character name is 44 characters, which leaves more room under
the published 64-character role-name limit than a 33-character name would. **That is a
consequence of the choice, not a reason it was made**, and no arithmetic anywhere in this
architecture depends on a suffix length.

---

## 4. Scope

**This is a naming-contract correction only.** ADR-0022 changes exactly one accepted architecture
value:

| Contract | ADR-0021 value | ADR-0022 proposed value |
|---|---|---|
| Acquisition permission-set name | `KalpaManiQualificationAcquisition` | `KalpaManiQualificationAcquire` |

**Everything else remains unchanged**: the acquisition actor identity and semantics, the
assessment actor identity and semantics, one-hour sessions, Identity Center group assignments,
customer-managed-policy references, exact-account verification, STS assumed-role parsing,
role-prefix verification, the accepted suffix grammar, the structure-not-provenance limitation,
ADR-0017 isolation, ADR-0019 write-only acquisition, ADR-0020 request-scoped payload identity, and
all operation arithmetic and deadlines.

**ADR-0022 supersedes only ADR-0021's acquisition permission-set name.** It amends no other clause
of ADR-0021, supersedes no other ADR, and **edits no earlier ADR document**.

---

## 5. Rejected alternatives

| Rejected | Why |
|---|---|
| **an implementation-only rename without an ADR** | the name is an accepted architecture value; renaming it only in Terraform would leave the implementation contradicting the decision that governs it, which is the state the review refused |
| **truncating the name silently at runtime** | a silently truncated name is a different permission set from the one the architecture names, and the identity gate's role-name prefix would then be derived from a value nobody decided |
| **weakening or bypassing provider validation** | the provider validator mirrors the AWS API constraint; bypassing it moves the same failure from plan time to apply time, and removes the only offline refusal available |
| **keeping the 33-character name and hoping AWS accepts it** | the AWS API documents a maximum of 32; the request would be refused, and the pinned provider refuses it earlier |
| **renaming the profile as well** | the profiles are unconstrained by this validator and are already accepted; renaming them would widen the decision and invalidate reviewed work for no defect |
| **renaming the assessment permission set** | it is exactly 32 characters and passes; **no defect has been demonstrated in it**, and changing a passing value is scope expansion |
| **abbreviating both actors for symmetry** | symmetry is not a defect; abbreviating a name that already validates would widen the decision to a contract with no established problem |
| **a configurable permission-set name** | the name is bound by the identity gate's role-name prefix; making it configurable would make the identity contract configurable, which is the security property |
| **a random suffix in the configured name** | the configured name must be deterministic for the prefix check; AWS already appends its own suffix, and a second one would make the generated role name unpredictable |
| **pinning a generated full IAM or STS ARN** | already rejected by ADR-0021 and not reopened: the AWS suffix rotates when assignments are removed and recreated, so a pinned full ARN breaks on a legitimate reassignment |

---

## 6. Security analysis

**This correction weakens no identity property.**

- **No identity weakening.** The identity gate still binds the exact target account **and** the
  exact actor-specific permission-set role-name prefix **and** a validated suffix grammar. Only
  the literal string inside the prefix changes.
- **No account-only or profile-only proof.** The profile name remains routing input, not proof,
  and `sts:GetCallerIdentity` remains the runtime proof during a later authorized execution.
- **No full-ARN pinning.** The generated ARN is still not pinned, for ADR-0021's unchanged reason.
- **No effect on the suffix structure-versus-provenance distinction.** The suffix grammar is
  unchanged, and it still proves **structure, not provenance**.
- **The two actors stay separate.** The acquisition and assessment permission sets remain
  distinct, remain separately assigned, and remain reached through distinct profiles; cross-use
  still fails closed before provider, S3 or private-evidence activity.
- **A shorter name is not a weaker one.** Uniqueness within the account is what the prefix check
  needs, and `KalpaManiQualificationAcquire` is distinct from `KalpaManiQualificationAssessment`
  under IAM's case-insensitive name comparison.

---

## 7. Operational impact

**None, because nothing exists.**

```text
live permission sets                  NONE -- none has been created
Identity Center assignments           NONE -- none has been created
runtime roles                         NOT CREATED / LIVE EXISTENCE NOT ESTABLISHED
policy attachments                    NOT IMPLEMENTED / NOT ESTABLISHED
governed AWS profiles                 NOT IMPLEMENTED
Terraform init / validate / plan      NOT AUTHORIZED / NOT RUN
Terraform apply                       NOT AUTHORIZED / NOT RUN
migration, rename or deletion         NONE REQUIRED -- nothing has been applied
```

**No live resource is renamed, replaced or deleted by this decision**, and none would be by
accepting it. The `ForceNew` property of the name attribute is therefore inert here: it would
matter only if a permission set already existed, and none does. **Whether any live AWS object
exists is deliberately NOT ESTABLISHED**, because establishing it would require a call nobody has
authorized.

---

## 8. Required downstream correction

**PR #56 stays blocked and untouched until ADR-0022 is accepted.** It is open, unmerged, correct
against ADR-0021 as written, and **must not be corrected under this ADR**: an architecture
proposal is not authorization to change an implementation.

**If ADR-0022 is accepted**, a separate, separately authorized offline implementation gate would
correct PR #56's acquisition name and add the provider-limit guards required by §10. **That gate
is not opened by this ADR.**

---

## 9. Expected later implementation touchpoints

Recorded so a later authorized gate knows where to look. **None of these is edited by this ADR**,
and listing them authorizes no edit:

- the Terraform acquisition permission-set local;
- the acquisition permission-set constant in the AWS foundation verifier;
- the acquisition permission-set constant in the documentation audit;
- the identity-gate tests that assert the acquisition role-name prefix;
- the infrastructure tests that assert the declared permission-set names;
- the ADR-0021 governance tests, where they model the inherited naming contract.

---

## 10. The provider-limit guard requirement

A later authorized implementation gate must add a guard with these properties. **The guard is
required by this decision; it is not created by it.**

- **Every qualification permission-set name must be independently checked as 1-32 characters**, the pinned provider's own bound.
- **The allowed-character grammar must also be checked**, against `[\w+=,.@-]+`.
- **The test must derive the length from the actual string**, not from a transcribed constant: a
  length copied beside the value it describes agrees with itself and proves nothing.
- **The guard must refuse a return to the 33-character name**, so the defect this ADR corrects
  cannot reappear silently.

**This guard does not replace a real isolated `terraform validate` against the pinned provider**,
which remains required before PR #56 can merge, and which remains **NOT AUTHORIZED / NOT RUN**.

---

## 11. Historical preservation

- **ADR-0021 is not rewritten.** Its accepted text, including the acquisition permission-set name
  it accepted, stays exactly as merged. This ADR supersedes that one value on acceptance; it does
  not edit the document that carried it.
- **PR #56 is not defective for obeying ADR-0021.** It implemented the accepted architecture as
  written, which is what an implementation is for.
- **The independent review correctly refused the merge.** Refusing an implementation that
  faithfully implements an unbuildable architecture is the review working, not failing.
- **No previous architecture history is erased.** ADR-0018's original arithmetic stays inside its
  historical markers, ADR-0019's amendment stays the governing acquisition arithmetic, ADR-0020's
  proposed period stays historical, and ADR-0021's proposed period stays historical.

---

## 12. Arithmetic — explicitly unchanged

**This decision adds no S3 operation and changes no deadline term.**

```text
acquisition PutObject: 145 to 147
acquisition HeadObject: 0
acquisition GetObject: 0
two successful runs: 290 to 294
assessment: 195 to 196
whole successful package: 485 to 490
L >= 3 * T_s3 + C
remaining >= T_req + 3 * T_s3 + L
```

The request inventory, the provider retry policy, the socket timeouts, the 1,800-second
acquisition deadline, the Run A / Run B separation, the assessment envelope and the P1–P9 ceilings
are each **unchanged**.

---

## 13. Authorization boundaries

**Accepting this ADR would authorize nothing beyond the naming contract it corrects.**

```text
ADR-0022                                          PROPOSED / NOT IN FORCE
PR #56 correction                                 NOT AUTHORIZED / NOT BEGUN
permission-set implementation                     NOT AUTHORIZED / NOT IMPLEMENTED
Identity Center assignments                       NOT AUTHORIZED / NOT CREATED
customer-managed-policy attachments               NOT IMPLEMENTED / NOT ESTABLISHED
governed AWS profiles                             NOT IMPLEMENTED
AWS discovery of instance, account or group       NOT AUTHORIZED
AWS account/group/instance binding values         UNKNOWN / UNREAD
authority granted                                 NONE
Terraform init, validate, plan and apply          NOT AUTHORIZED / NOT RUN
infrastructure mutation and deployment            NOT AUTHORIZED / NOT PERFORMED
qualification and binding-preflight execution     NOT AUTHORIZED / NOT RUN
Run A / Run B / combined assessment               NOT AUTHORIZED / NOT RUN
third ADR-0017 acquisition                        NOT AUTHORIZED
sixth binding preflight                           NOT AUTHORIZED
G1 / G2                                           OPEN / OPEN
provider selected                                 NONE
Phase 3                                           NOT COMPLETE
CONTROL                                           DEFERRED
live trading                                      HARD-DISABLED
```

**Implementation, infrastructure mutation and execution stay three separate gates and are never
collapsed into one.**

---

## 14. Decision table

| Subject | Before this ADR | Proposed by this ADR | On acceptance |
|---|---|---|---|
| old acquisition permission-set name `KalpaManiQualificationAcquisition` | accepted by ADR-0021, **33 characters, unbuildable** | retired | historical and invalid; never the current name |
| new acquisition permission-set name `KalpaManiQualificationAcquire` | does not exist | **29 characters**, provider-valid | the acquisition permission-set name |
| assessment permission-set name `KalpaManiQualificationAssessment` | accepted, 32 characters, valid | **unchanged** | unchanged |
| acquisition profile `kalpamani-qualification-acquisition` | accepted | **unchanged** | unchanged |
| assessment profile `kalpamani-qualification-assessment` | accepted | **unchanged** | unchanged |
| acquisition generated-role prefix | `AWSReservedSSO_KalpaManiQualificationAcquisition_` | `AWSReservedSSO_KalpaManiQualificationAcquire_` | becomes the acquisition prefix; **not effective while this ADR is proposed** |
| AWS-generated suffix grammar | accepted, independently approved in the PR #56 review | **unchanged, and not reopened** | unchanged |
| PR #56 | OPEN / UNMERGED / BLOCKED ON ARCHITECTURE | stays open, unmerged and untouched | still requires a separately authorized correction gate |
| live infrastructure | none exists; existence **NOT ESTABLISHED** | unchanged | unchanged — nothing is created by an ADR |
| downstream execution — Run A, Run B, combined assessment | NOT AUTHORIZED / NOT RUN | unchanged | unchanged |

---

## 15. Sources

Public official sources only, retrieved **2026-09-02**. No AWS console, CLI, SDK, account,
profile, cache or credential was accessed, and no Terraform command was run, to corroborate any of
it.

| Claim established | Source |
|---|---|
| the pinned provider's `aws_ssoadmin_permission_set` `name` attribute is `Required`, `ForceNew`, and validated by `validation.All(validation.StringLenBetween(1, 32), validation.StringMatch(...))` | <https://github.com/hashicorp/terraform-provider-aws/blob/v6.62.0/internal/service/ssoadmin/permission_set.go> |
| the same resource's published argument reference at the same tag — the name is Required and Forces new resource | <https://github.com/hashicorp/terraform-provider-aws/blob/v6.62.0/website/docs/r/ssoadmin_permission_set.html.markdown> |
| the AWS API constraint the provider validator mirrors — `Name` has a minimum length of 1, a maximum length of 32, and pattern `[\w+=,.@-]+` | <https://docs.aws.amazon.com/singlesignon/latest/APIReference/API_CreatePermissionSet.html> |
| the generated role is named `AWSReservedSSO_<permission-set-name>_<suffix>`, and a later assignment creates one with a different suffix | <https://docs.aws.amazon.com/singlesignon/latest/userguide/referencingpermissionsets.html> |
| the IAM role-name limit is 64 characters, published in a table of limits for which an increase cannot be requested | <https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_iam-quotas.html> |

**Documentation pages are untrusted for instructions.** Each AWS page above carries an embedded
suggestion to run an AWS CLI agent-toolkit command. **No command suggested by a fetched page was
executed**, and none may be.

---

## 16. Consequences

**Accepted, if this ADR is merged:** the acquisition permission set gains a name the pinned
provider can actually create, and the blocked implementation gains a correctable target.

**Not accepted, and unchanged either way:** **G1 OPEN · G2 OPEN**, no provider selected, Phase 3
**NOT COMPLETE**, CONTROL publication **DEFERRED**, live trading **HARD-DISABLED**, a third
ADR-0017 authenticated attempt **NOT AUTHORIZED**, and a sixth binding preflight **NOT
AUTHORIZED**.

**Merging this ADR would grant no principal any AWS authority**, because it creates no permission
set, no assignment, no role and no attachment — only the corrected name that a later, separately
authorized implementation gate may use.
