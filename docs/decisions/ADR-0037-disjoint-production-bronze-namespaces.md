# ADR-0037 — Disjoint production Bronze namespaces

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0037 is proposed and carries no authority.
That is a statement about the present, it will remain true of these days after any later merge, and it
is not to be rewritten as though this decision had authority before it was accepted. On merge, this ADR
becomes **ACCEPTED / IN FORCE** as **a narrow amendment of ADR-0036's production Bronze prefixes and
nothing else**, effective together with the offline declaration that implements it.

**The condition above has since been satisfied.** **PR #94 merged** — merged **2026-09-12T12:16:47Z**, merge
commit **`7d7cad34454a670c701e615bb7d26a70533118ee`**, ordered parents **`066a93d8780aa6fc06354ed096fa69c34496b10d`** then
**`70e365554fa8ad3b8aa5a4b37bbf56ad2b61bc4c`**, with a **merge tree identical to the independently reviewed pull-request head
tree** (`3f312e359d4f8e655f44dd57df3d4cfbd9bf8b94`). ADR-0037 is therefore **ACCEPTED / IN FORCE** as a narrow amendment of
ADR-0036's production Bronze prefixes, effective together with the offline declaration merged beside it.
While the pull request was open it was proposed and carried no authority — true then, and not rewritten.
**Acceptance applied nothing and materialized nothing**: the declaration it amends stays
**DECLARED / OFFLINE-VALIDATED / NOT PLANNED / NOT APPLIED / NOT AUTHORIZED TO APPLY**, and the production
key builders that spell these namespaces in code were written afterwards, under their own authorization,
exercised only on synthetic inputs.

**Nothing was run to produce this decision.** No AWS call, no Terraform plan or apply, no read of any
licensed object. The evidence is the merged key builders in the repository and the accepted ADRs that
describe them.

---

## 1. Context — the overlap, traced

[ADR-0036](ADR-0036-production-data-plane-principals-and-trust-model.md) §2.2 and §2.4 name the
production acquisition actor's write prefixes, and §2.7 puts them under the licensed bucket's
conditional-write `Deny` statements:

```text
licensed/bronze/sharadar/<dataset>/objects/sha256/*
licensed/bronze/sharadar/<dataset>/acquisitions/*
licensed/bronze/sharadar/_indexes/*
licensed/bronze/_acquisition_claims/*
```

Three of those four are not new namespaces. They are the general Bronze bridge's, accepted by
[ADR-0009](ADR-0009-sharadar-provider-realistic-implementation.md) and
[ADR-0011](ADR-0011-implement-the-licensed-s3-research-object-store.md) and implemented in
`src/kalpamani/data/ingest/publication.py`, and they already hold objects:

| Key builder | Physical key | Written by |
|---|---|---|
| `bronze_payload_key` | `bronze/sharadar/<dataset>/objects/sha256/<digest>` | ADR-0017's completed attempt two (one payload) |
| `bronze_acquisition_key` | `bronze/sharadar/<dataset>/acquisitions/<digest>/<run-id>.json` | ADR-0017 attempt two; **every ADR-0018 qualification record** (Run A and Run B, 96 objects) |
| `acquisition_claim_key` | `bronze/_acquisition_claims/<digest>/<run-id>.json` | ADR-0017 attempt two; **every ADR-0018 qualification claim** (96 objects) |

Only the qualification *payloads* live under a prefix of their own
(`bronze/sharadar/<dataset>/qualification/…`, [ADR-0020](ADR-0020-request-scoped-qualification-payload-identity.md)),
and only those did ADR-0036 exclude from the production scope. So as accepted, a production actor's
`PutObject` grant reached the qualification record and claim namespaces, and the production bucket-policy
statements governed prefixes the qualification package writes to. Conditional writes made the overlap
functionally harmless — no existing object could be overwritten — but it was an overlap of **authority and
of accounting**, and ADR-0036's own §2.7 sentence that the qualification prefixes were "not in scope" was
not true of records and claims.

## 2. Decision

**Production Bronze objects live under namespaces no earlier package writes.** ADR-0036 §2.2, §2.3, §2.4
and §2.7 are amended to read, wherever they name the production acquisition prefixes:

```text
payloads   licensed/bronze/sharadar/<dataset>/production/objects/sha256/<digest>
records    licensed/bronze/sharadar/<dataset>/production/acquisitions/<...>
locator    licensed/bronze/sharadar/_indexes/<run-id>.json          (unchanged; production-only already)
claims     licensed/bronze/_production_claims/<...>
outputs    licensed/silver/*, licensed/gold/*, licensed/manifests/*  (unchanged; production-only already)
```

The `production/` path segment under each dataset and the `_production_claims` namespace are the whole of
the change. Consequences, each of them what the traced layouts require:

1. **No production grant names an earlier namespace.** The general Bronze payload, record and claim
   prefixes and every qualification prefix appear in the production policies **only in `Deny` statements**,
   for every S3 action.
2. **No production bucket-policy statement governs an earlier namespace.** The §2.7 scope is the five
   production namespaces above plus the `_verification/` prefix, enumerated; `bronze/sharadar/*` is never
   used as a scope.
3. **No existing object moves.** Qualification records, claims, payloads, locators and reports and
   ADR-0017's three objects stay exactly where they are, under exactly the policies that wrote them.
4. **The general Bronze bridge is unchanged.** `publication.py` keeps its key builders; the production
   runner needs production key builders of its own, under the ADR-0036 application gate.
5. **The deletion runbook** gains `bronze/sharadar/<dataset>/production/` and `bronze/_production_claims/`
   as expected prefixes; both are inside `bronze/`, which prefix-based deletion already covers.

**Evidence, checkable.** `tests/unit/test_production_infrastructure.py` builds the earlier packages' keys
with the **merged key builders** on synthetic inputs — `bronze_payload_key`, `bronze_acquisition_key`,
`acquisition_claim_key`, `qualification_payload_key`, `locator_key_segments`, `report_key_segments` — and
proves that no production `Allow` matches any of them, that every one of them matches a production
`Deny`, and that no production bucket-policy statement's scope matches any of them, while a
production-shaped key does.

## 3. What this ADR does not do

It does not rewrite ADR-0036's accepted text; ADR-0036 stands, and this amendment governs where the two
differ once it is in force. It does not touch ADR-0009, ADR-0011, ADR-0017, ADR-0018, ADR-0019 or ADR-0020,
or any object they produced. It authorizes no application, no run and no read. G2 OPEN; CONTROL DEFERRED;
Phase 3 NOT COMPLETE; live trading HARD-DISABLED.

## 4. Rejected alternatives

- **Keep the shared prefixes and rely on conditional writes.** Rejected: a grant that can create objects
  in another package's namespace is an authority overlap whatever the write semantics, and the accounting
  of the qualification package would sit under a production policy.
- **Move the qualification records and claims instead.** Rejected: 192 objects the combined assessment
  already read and reported on would change key; the accepted evidence must stay where its locators say
  it is.
- **Change only the words in ADR-0036 §2.7.** Rejected: the finding was the overlap, not the sentence.
