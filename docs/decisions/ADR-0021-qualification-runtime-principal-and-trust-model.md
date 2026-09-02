# ADR-0021 — Qualification runtime principal and trust model

**Status: PROPOSED — no authority until the pull request introducing this ADR is independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0021 is proposed and carries no
authority. That is a statement about the present, it will remain true of these days after any
later merge, and it is not to be rewritten as though this decision had authority before it was
accepted.

**This decision chooses architecture only.** It implements nothing, creates nothing, inspects
nothing, binds nothing, deploys nothing, plans nothing and runs nothing. No AWS identity,
account, profile, credential, cache, permission set, assignment, role, trust policy or policy
attachment was read, created, modified or verified in producing it, and none may be read,
created, modified or verified by accepting it.

---

## 1. Context

[ADR-0018](ADR-0018-bounded-private-empirical-sharadar-qualification.md) designed a bounded
private empirical qualification with two least-privilege actors — an **acquisition** actor that
writes evidence and an **assessment** actor that reads it.
[ADR-0019](ADR-0019-write-only-acquisition-collision-policy.md) amended the acquisition side to
be write-only at the IAM layer, after a feasibility review established that AWS authorizes
`HeadObject` through `s3:GetObject` and publishes no independent metadata action.
[ADR-0020](ADR-0020-request-scoped-qualification-payload-identity.md) re-scoped the
qualification payload key to the execution identity, the request ordinal and the payload digest.

PR #52 then merged the two permission sets those decisions describe, as Terraform
`aws_iam_policy` declarations — **and deliberately stopped there.** It chose no runtime trust
principal and created no role or attachment, because accepted authority did not determine one,
and inventing an ECS, Lambda, EC2, federated or human trust principal in a Terraform file would
have been an architecture decision taken in the wrong place. The merged status recorded the
consequence plainly: **the next architecture gate must choose the execution principal and trust
model before roles or attachments can be designed.**

**This ADR is that gate, and nothing wider.** It supersedes no prior ADR. It narrows the
unresolved identity and trust boundary left by ADR-0018, ADR-0019, ADR-0020 and PR #52, and it
amends the text of none of them.

### 1.1 What the repository already establishes

Each of the following was established by static reconciliation against committed code, without
contacting AWS:

| | |
|---|---|
| the two qualification actors are **acquisition** and **assessment** | ADR-0018 §10, ADR-0019 §4.1 |
| their permission policies are **distinct and intentionally asymmetric** | `infra/aws/research-data-plane/qualification_policies.tf` |
| the operator entry points **pin a governed AWS profile and pass the governed identity gate** | `scripts/sharadar_empirical_qualification.py`, `scripts/sharadar_qualification_assessment.py` |
| **application source makes no explicit `sts:AssumeRole` call** | no occurrence exists under `src/` or `scripts/` |
| source control contains **no qualification role, permission-set assignment, custom trust policy or policy attachment** | `infra/aws/research-data-plane/` |
| **no live AWS existence is established** | establishing it would take an AWS call, which is not authorized |

The existing governed identity gate compares the **account** returned by
`sts:GetCallerIdentity` against a local account binding, and pins one profile constant. **It
does not evaluate the caller's role identity at all.** That is recorded here as a finding, and
it is the one proven implementation consequence of this decision — see §8.

---

## 2. Decision

**AWS IAM Identity Center is the human authentication root.** No IAM user or long-lived access
key is permitted for qualification.

**A dedicated, governed Identity Center operator group is the assignment subject.** The exact
identity-store and group identifier is an environment-binding value and remains unknown and
unread in this decision.

**Two separate permission sets exist logically:**

```text
KalpaManiQualificationAcquisition
KalpaManiQualificationAssessment
```

**Each permission set is assigned to the governed operator group in the single target account
that already owns the licensed data plane.** The account id is an environment-binding value and
must not appear in this proposal.

**Each assignment causes IAM Identity Center to create and manage a distinct runtime IAM role in
that account.**

**The acquisition permission set references only the merged acquisition managed-policy
declaration from PR #52.** **The assessment permission set references only the merged assessment
managed-policy declaration from PR #52.** Neither policy's action or resource matrix is changed
by this decision.

**No custom `aws_iam_role`, custom role trust policy, source-profile role chain, application
AssumeRole, IAM user, access key, ECS task role, Lambda execution role, EC2 instance profile,
web-identity principal or cross-account principal is part of this architecture.**

**Application entry points continue to use two exact named profiles:**

```text
kalpamani-qualification-acquisition
kalpamani-qualification-assessment
```

**Those profiles use the SDK's IAM Identity Center credential provider and return short-lived,
refreshable credentials for their corresponding permission-set role.**

**The acquisition entry point accepts only the acquisition permission-set role identity, and
assessment accepts only assessment.** **Cross-use fails closed before provider, S3 or
private-evidence activity.**

**The identity gate binds the exact target account plus the exact permission-set role-name
prefix and a validated AWS-generated suffix grammar.** **It does not pin one full generated role
ARN forever, because the suffix may rotate when assignments are removed and recreated.**

**The profile name is routing input, not proof.** **`sts:GetCallerIdentity` remains the runtime
proof during a later authorized execution.**

**Credentials from default-profile fallback, environment access keys, shared long-lived
credential files, a differently named SSO role, or any other provider chain are refused.**

**Session duration is bounded to one hour per permission set.** **That covers the 1,800-second
run deadline with operational margin without authorizing an unbounded session**, and one hour is
also the AWS default rather than a raised ceiling.

**Role separation is a process and permission separation, not a claim that two different humans
approve the two stages.** **One governed operator may be assigned both permission sets but must
invoke each actor under its correct profile**, and no process ever holds the union of the two
permission sets.

---

## 3. Trust model

**The governed Identity Center group assignment is the authorization binding.** Authority
travels group, then permission set, then assignment, then generated role, and there is no other
path into the qualification permissions.

**IAM Identity Center manages the generated role and its service trust, and KalpaMani does not
author a custom trust policy under this decision.** AWS states that Identity Center owns and
secures these roles, that only Identity Center can modify them, that only users in Identity
Center can assume them, and that their role trust policy cannot be modified to admit principals
outside Identity Center. That is a stronger property than a hand-written trust policy could
give, and it is one this repository does not have to maintain.

**The two permission sets, account assignments, customer-managed-policy references, session
durations and the profile contract are the later implementation surface.**

**Removing all assignments may delete and later recreate the generated role with a new suffix**,
so the identity gate uses the stable permission-set role prefix plus strict account binding
rather than a stale full ARN. AWS's own guidance for referencing these roles uses a wildcard in
place of the unique suffix for exactly this reason.

**No live assignment, permission set, role or policy attachment exists merely because this
decision describes it.** Whether any such object exists in AWS is **NOT ESTABLISHED**, and
establishing it is a separate authorization.

### 3.1 The generated role shape

Written as a shape, with placeholders, and never as a value:

```text
name  AWSReservedSSO_<permission-set-name>_<aws-generated-suffix>
arn   arn:aws:iam::<target-account-id>:role/aws-reserved/sso.amazonaws.com/<governed-region>/AWSReservedSSO_<permission-set-name>_<aws-generated-suffix>
```

The `<governed-region>` path component is absent when the Identity Center identity source is
hosted in `us-east-1`, so the contract must admit both shapes rather than requiring the region
segment.

**The suffix grammar validates structure, not provenance.** AWS documents the suffix as unique
and generated, and its published examples are lowercase hexadecimal; AWS publishes no formal
grammar for it. The contract therefore requires a non-empty suffix of the documented shape and
**does not claim AWS guarantees that shape** — a string that merely looks like a generated
suffix is lexically indistinguishable from one, and nothing can separate them.

---

## 4. Sample configuration — architecture, not a file

**The sample is architecture, not a file to create in this task.** No profile is created,
written, edited or inspected by this decision.

```text
[profile kalpamani-qualification-acquisition]
sso_session = <governed-sso-session>
sso_account_id = <target-account-id>
sso_role_name = KalpaManiQualificationAcquisition
region = <governed-region>

[profile kalpamani-qualification-assessment]
sso_session = <governed-sso-session>
sso_account_id = <target-account-id>
sso_role_name = KalpaManiQualificationAssessment
region = <governed-region>
```

**No actual account, start URL, region, user, group, role ARN, session, credential, bucket, key
or secret appears anywhere in this document**, and none may be added to it. `sso_role_name`
takes the **permission-set name**, not a role ARN, which is what makes the profile contract
survive suffix rotation.

---

## 5. Identity decision table

Exhaustive over the cases this architecture must answer. **Every refusal is a refusal before
provider, S3 or private-evidence activity.**

| # | Observed identity situation | Outcome |
|---|---|---|
| 1 | correct acquisition profile and acquisition role | the identity gate may pass |
| 2 | correct assessment profile and assessment role | the identity gate may pass |
| 3 | acquisition profile resolving to assessment role | refuse |
| 4 | assessment profile resolving to acquisition role | refuse |
| 5 | correct profile name but wrong account | refuse |
| 6 | correct account but wrong role prefix | refuse |
| 7 | valid role prefix with a malformed or missing generated suffix | refuse |
| 8 | a prior full ARN after suffix rotation | do not pin; evaluate the new valid identity against the stable contract |
| 9 | default profile | refuse |
| 10 | no profile | refuse |
| 11 | environment access key credentials | refuse |
| 12 | IAM user principal | refuse |
| 13 | ECS, Lambda, EC2 or other service principal | refuse |
| 14 | custom chained role | refuse |
| 15 | expired or absent SSO session | fail before execution, and never fall back |
| 16 | group unassigned from the permission set | no credentials; fail closed |
| 17 | one operator assigned both permission sets | allowed only through actor-specific profiles, with no permission union in one process |
| 18 | unknown or unparseable caller identity | refuse |

Case 1 and case 2 say **may pass**, never **passes**: a correct identity satisfies this gate and
nothing else, and every later gate still applies.

---

## 6. Rejected alternatives

| Alternative | Why it is rejected |
|---|---|
| **long-lived IAM user or access keys** | AWS distinguishes IAM users, which hold long-term credentials, from Identity Center users, which are granted temporary credentials generated at each sign-in. A long-lived key for a licensed-data actor is a standing credential that must be rotated and revoked by hand, and §4.4 of the operating rules forbids storing one at all |
| **one shared role or permission set for both actors** | it destroys the ADR-0018 §10.3 compromise argument. A single principal holding both matrices could read licensed objects **and** reach a provider, so a provider failure could be converted into an assessment result and a compromised acquisition process could exfiltrate the store |
| **an SSO source role chained into custom qualification roles** | it introduces an extra `sts:AssumeRole` permission surface and a hand-written trust policy, without an accepted requirement, when direct Identity Center permission-set roles already provide two distinct short-lived principals |
| **direct custom IAM roles with hand-written trust policies** | the same extra trust-policy surface, plus KalpaMani would then own and have to maintain the correctness of the trust boundary that Identity Center otherwise owns and makes unmodifiable |
| **ECS, Lambda, EC2, OIDC or other service and workload principals** | the merged entry points are operator surfaces that pin a profile and call no `sts:AssumeRole`, so a service principal contradicts the accepted execution model. AWS also states that permission-set access cannot be assigned to IAM users, federated users or service accounts, so such a principal could not use these permission sets at all |
| **cross-account execution** | the licensed data plane is one account, and a second account adds a trust boundary that carries no accepted requirement |
| **pinning the complete generated `AWSReservedSSO_*_<suffix>` ARN forever** | AWS documents that deleting every assignment deletes the generated role, and that a later assignment creates a new role with a **different** unique suffix. A pinned full ARN goes stale on rotation and disrupts access, which is why AWS's own referencing guidance wildcards the suffix |
| **trusting the whole AWS account without a narrower identity contract** | the account already contains the ECS task, task-execution and deletion roles. Account-only binding is what the existing gate does today, and it cannot tell the acquisition actor from the assessment actor, or either from an unrelated principal |
| **profile-name-only authorization** | a profile name is local configuration text that any caller can write. It selects a credential source; it proves nothing about the identity that results |
| **environment-variable credential fallback** | it silently overrides the profile, which is precisely the wrong-account hazard §4.24 of the operating rules exists to prevent, in its AWS form |

---

## 7. What this decision preserves, unchanged

**The decision changes no application behaviour, no stored data and no arithmetic.** It changes
who runs the code, never what the code does.

| | |
|---|---|
| **ADR-0019 write-only acquisition** | unchanged |
| **conditional `PutObject` collision behaviour** | unchanged — a 412 still fails closed and establishes nothing about the occupying content |
| **zero acquisition `HeadObject`, `GetObject`, `GetObjectAttributes` and listing** | unchanged |
| **ADR-0020 execution, request and digest scoped payload identity** | unchanged |
| **assessment digest recomputation and key reconstruction** | unchanged |
| **ADR-0017, the shared store and ingestion behaviour** | unchanged |
| **the durable locator schema** | unchanged — no field is added, removed or reinterpreted |
| **the existing bucket, the SSE-S3 choice, the deletion model and the KMS boundary** | unchanged |
| **the S3 action and resource matrices in the two PR #52 policy declarations** | unchanged |
| **the 1,800-second deadline, the request inventory, the retry policy, the socket timeouts, the operation accounting and the assessment envelope** | unchanged |

The governing arithmetic is preserved exactly:

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

**The identity and trust decision adds no S3 operation and changes no deadline term.** An
identity is established before the acquisition execution phase begins, in the stages ADR-0018
places ahead of stage 11, so it consumes none of the deadline it protects.

---

## 8. Later gates, explicitly separate

**Acceptance of ADR-0021 would authorize architecture only.** It would not authorize or perform:

```text
discovery of actual Identity Center instance, identity store, account, group,
    assignment, profile or region values
Terraform implementation of permission sets or assignments
policy attachment implementation
identity-gate code changes
profile creation
Terraform init, validate, plan or apply
AWS policy, role or assignment creation
deployment, binding preflight, qualification, Run A, Run B or assessment
```

**The next gate after ADR acceptance is an offline implementation gate** for permission sets,
customer-managed-policy attachments, assignments, and any proven identity-gate and
profile-contract corrections.

**One identity-gate correction is proven necessary, and is recorded rather than invented.**
Static reconciliation establishes that `identity_gate()` in `scripts/aws_foundation_verify.py`
compares only the returned **account** against a local binding, and that all four operator entry
points pin the single constant `kalpamani-foundation`. Neither the two-profile contract nor the
role-identity contract in §2 can be satisfied by that code as committed. **This ADR does not
change it**, does not specify its diff, and does not authorize the change; it records that the
later implementation gate has real work to do, so that gate is not mistaken for a formality.

**Implementation, infrastructure mutation and execution stay three separate gates and are never
collapsed into one.**

---

## 9. Sources

Public official AWS documentation only, retrieved **2026-09-01**. No AWS console, CLI, SDK,
account, profile, cache or credential was accessed to corroborate any of it.

| Claim established | Source |
|---|---|
| a permission set is a template of IAM policies; assigning one creates Identity Center-controlled IAM roles in each account and attaches the permission set's policies to them; session duration defaults to one hour, to a maximum of twelve | <https://docs.aws.amazon.com/singlesignon/latest/userguide/permissionsetsconcept.html> |
| customer managed policies must be created in advance in each target account, matching name and path, and Identity Center attaches them to the role it creates | <https://docs.aws.amazon.com/singlesignon/latest/userguide/howtocmp.html> |
| the generated role is named `AWSReservedSSO_<permission-set-name>_<unique-suffix>`; deleting every assignment deletes the role, and a later assignment creates one with a **different** suffix; AWS recommends wildcarding the suffix rather than pinning a full ARN | <https://docs.aws.amazon.com/singlesignon/latest/userguide/referencingpermissionsets.html> |
| SDKs and tools resolve Identity Center credentials from a named profile via `sso_session`, `sso_account_id`, `sso_role_name` and `region`; `sso_role_name` takes the permission-set **name**, not a role ARN; the credentials are short-term and automatically refreshed | <https://docs.aws.amazon.com/sdkref/latest/guide/feature-sso-credentials.html> |
| the AWS CLI profile form of the same configuration, and the `aws sso login` flow that populates it | <https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html> |
| Identity Center owns and secures permission-set roles, only Identity Center can modify them, permission-set access cannot be assigned to IAM users, federated users or service accounts, and their trust policy cannot be modified to admit principals outside Identity Center | <https://docs.aws.amazon.com/singlesignon/latest/userguide/howtogetcredentials.html> |
| temporary credentials are short-term, are not stored with the user, and need no rotation or explicit revocation | <https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_temp.html> |
| a custom IAM role requires a hand-written trust policy naming its principals, which is the surface the rejected alternatives would add | <https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_elements_principal.html> |

**Documentation pages are untrusted for instructions.** Each of these pages carries an embedded
suggestion to run an AWS CLI agent-toolkit command. **No command suggested by a fetched page was
executed**, and none may be.

---

## 10. Consequences

**Accepted, if this ADR is merged:** the runtime principal question that blocked qualification
infrastructure design is answered, and the two merged policy declarations gain a named holder
they do not yet have.

**Not accepted, and unchanged either way:** **G1 OPEN · G2 OPEN**, no provider selected,
Phase 3 **NOT COMPLETE**, CONTROL publication **DEFERRED**, live trading **HARD-DISABLED**, a
third ADR-0017 authenticated attempt **NOT AUTHORIZED**, and a sixth binding preflight **NOT
AUTHORIZED**.

**Merging this ADR would grant no principal any AWS authority**, because it creates no
assignment, no role and no attachment — only the architecture that a later, separately
authorized implementation gate may build.
