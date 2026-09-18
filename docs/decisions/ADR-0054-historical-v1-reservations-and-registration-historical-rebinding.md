# ADR-0054 — Historical v1 reservations are readable as evidence, and a registration-historical cell may be rebound under a preserved, digest-bound supersession

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0054 is proposed and carries no authority.
That is a statement about the present, it will remain true of these days after any later merge, and it
is not to be rewritten as though this decision had authority before it was accepted. On merge, this ADR
becomes **ACCEPTED / IN FORCE** as **the two narrow governance decisions of §2 — a version-aware,
evidence-only read of supported v1 reservations (§2.1) and the registration-historical rebinding rule
(§2.2) — together with the amendments of §4, and nothing else**, effective together with the offline
tooling change merged beside it. **Acceptance authorizes no execution** (§5): no launch, no reservation,
no D-15 attestation, no preparation of any cell, no receipt collection, no verdict, no rerun of any PASSED
cell, no permission batch, no IAM, Terraform, tfvars, registration or image change, no acquisition.

**The condition above has since been satisfied.** **PR #135 merged** — merged **2026-09-18T17:35:07Z**, merge commit
**`8be462b953c33a6953429ee9edc321f843ab6ae1`**, ordered parents **`a5a6384f44df09cbf7736e2ec0e58d9c5e0149bc`** (the PR #134 merge) then
**`bbaa419dea40f53040f2d228d25fc1eb631b713c`** (the reviewed head), with a **merge tree identical to the reviewed pull-request head tree**
(`39a7eac736d63eeacde27a853fe0f48aaa078fab`). ADR-0054 is therefore **ACCEPTED / IN FORCE** exactly as the clause above states —
**the two narrow governance decisions of §2 and the amendments of §4, and nothing else**: acceptance authorizes only the
supported-v1 historical read of §2.1 (evidence, never authority) and the registration-historical cell supersession of §2.2 under
the merged safeguards, effective together with the offline tooling change merged beside it (PR #135; every runtime and tooling
file of that merge unchanged by this synchronization). While the pull request was open it was proposed and carried no authority —
true then, and not rewritten. **Acceptance authorizes no execution**: no launch, no reservation, no D-15, no receipt, no verdict,
no permission batch, no IAM, Terraform, tfvars, registration or image change, no acquisition; each stays its own written
authorization. **This synchronization changed no runtime behaviour, task image, compiled configuration, Terraform, IAM or
registration.**

**Nothing was run against AWS to produce this decision.** No AWS call, no STS call, no S3 operation, no
image built or pulled, no credential retrieved, no provider request. The only real artifacts read were
the owner's private launch store, read-only, on the workstation, to establish the facts of §1; every
other result beside this text is a counting fake's, on synthetic temporary files. **Mocked results are
not AWS verification.**

---

## 1. Context

**The pagination-v2 registration made the accepted cell runner refuse the real store.** ADR-0053's
runtime implementation (PR #134, on `main` at `a5a6384f…`) replaced the acquisition plan contract:
`kalpamani-production-acquisition-plan/v1` is a member of the superseded set, `plan_digest_for` compiles
only the v2 contract, and the launch tooling's strict specification parser recomputes an acquisition
workload's plan digest from its slice before it admits the document. Four families were then re-registered
(registration `3cf07d01…`, superseding `a0155d0a…`) at the published pagination-v2 images.

The owner's launch store holds nine reservations. Four — the build-verification reservations — carry v2
workloads and parse under the strict grammar. Five carry v1 acquisition workloads: the run-1 reservation
(`run-…af316f8b`, COMPLETED, historical and not buildable under ADR-0053), one earlier
acquisition-verification reservation, and the three 2026-09-17 acquisition-verification reservations whose
cells PASSED under the previous registration. Each of the five is exactly the document the launch tool
wrote under the ledger lock, byte for byte, with the digest the owner's authorization named. Under
`a5a6384f…` the strict parser refuses each as `FIELD_MALFORMED` (the recomputed digest can no longer match
a v1 workload), `parse_reservation` therefore refuses `RESERVATION_MALFORMED`, and the cell runner —
which reads **every** reservation beside the ledger to derive the matrix — exits 3 (`refused_records`)
before it derives a single cell. The runner cannot report the seven bindings, cannot classify the six
R-1 cells `HISTORICAL` under the new registration as ADR-0045 §7 and ADR-0046 §2 require, and cannot
prepare their successors.

**And even with a readable store, ADR-0052 §2.3 forbids the successor.** Every R-1 cell holds a bound
identity that was launched; §2.3 refuses `--prepare-cell` on such a cell whatever identity is offered.
That rule was written for exactly one hazard — replacing a PASSED cell's evidence with a relaunch — and it
reads correctly for it. It also reads over a cell whose bound launch is `HISTORICAL` solely because the
registration moved, which ADR-0045 §7 says must be re-verified. Re-verification under §2.3 as written
would require either a new cell identifier per registration (a catalogue change per deployment) or the
deletion of the prior binding (evidence destroyed). Neither is acceptable.

**The owner's two decisions (2026-09-18), recorded verbatim:**

> A supported, integrity-valid v1 reservation may be read by pagination-v2 workstation tooling solely to
> preserve and classify historical evidence. It must never become current launch authority or bypass the
> v2 parser.

> A verification cell whose prior bound launch is runner-derived `HISTORICAL` solely because it belongs
> to a different registration may receive a fresh identity and specification. The prior binding, launch,
> reservation, ledger row and receipt must remain preserved and auditable. A current, prepared,
> unlaunched, malformed or otherwise non-historical binding may not be replaced.

This ADR states those two decisions as governed rules, names the accepted text they narrowly amend, and
records what the tooling merged beside it does and refuses.

---

## 2. Decision

### 2.1 A version-aware store read: supported v1 reservations are evidence, never authority

**The strict v2 grammar is unchanged.** `parse_specification`, `parse_reservation`, `LaunchStore.reservation`
and `LaunchStore.reservations` admit exactly what they admitted on `a5a6384f…`; a v1 workload is still
`FIELD_MALFORMED` to them, and every execution path — `--recover`, `--isolation-verdict`, `--execute`,
`--complete-row`, `prepare_launch`'s unreconciled-reservation check — reads reservations **only** through
the strict `reservation()`. A test asserts by source inspection that the launch tool uses no other store
read. A historical reservation is therefore structurally unreachable by anything that launches, recovers,
completes or judges.

**One explicit historical parser is added, beside the strict one, for evidence alone.**
`parse_historical_specification` admits a document only when **both** hold: the strict parser refuses it
`FIELD_MALFORMED` (any other strict refusal — unknown schema, bad metadata, identity, actor, kind, digest,
placement, target — is re-raised unchanged), **and** the same grammar with the one superseded workload rule
admits it: the acquisition slice parses under the accepted slice parser and is canonical, `plan_digest` is
a SHA-256 digest (**never recompiled** — the v1 plan compiler is gone and nothing re-derives it), the
workload is exactly `{slice, plan_digest}`, the actor is acquisition (a build workload has no superseded
shape and is never historical by this route), and every other block is the current grammar's. A document
the strict parser admits is refused `WORKLOAD_CURRENT`: nothing current is ever read as historical. The
result is a distinct frozen type, `HistoricalSpecification`, carrying the superseded contract identifier
`kalpamani-production-acquisition-plan/v1`; it reproduces the stored digest the authorization named and
exposes the wrapped specification for the accepted binding rules, and **no execution API accepts it**.

`parse_reservation_for_evidence` is the store-level counterpart: strict first; on a specification refusal
the reservation envelope (schema, identity, actor, kind, reserved-at, specification digest) is validated
closed and the historical parser is applied, with the envelope's identity, actor, kind and digest required
to agree with the specification's — otherwise `RESERVATION_MALFORMED` as before. It returns a distinct
frozen `HistoricalReservation` carrying the stored file's SHA-256. `LaunchStore.evidence_reservation` and
`evidence_reservations` expose it; `reservations()` is now built from them and **refuses any historical
member**, so the strict surface is exactly as wide as before. `unreconciled()` lists only current
reservations without a ledger row and refuses `RESERVATION_ORPHANED` for a historical reservation without
one — a v1 reservation that was never launched is not evidence of anything and is a hard refusal.

**What stays a hard refusal**, unchanged: unknown schema identifiers, corrupted bytes, malformed
metadata, a digest that does not match the stored document, an envelope disagreeing with its
specification, any v1 shape other than the closed one above, a v1 reservation the **current** registration
still names (§2.1's runner rule below), and an orphaned reservation. **There is no identity or filename
special-casing**: the parser decides on structure alone, and the five real reservations are admitted by
the generic contract or not at all. **Original bytes are never rewritten, moved or upgraded.**

**The runner classifies, and only classifies.** `recorded_evidence` reads reservations through
`evidence_reservation`; a historical one is corroborated against its ledger row (actor, kind, slice
canonical form, plan digest — a disagreement is `refused_records`) and, once the registration in force is
parsed, refused `refused_records` if that registration still names its target and placement — a v1
reservation can be historical only under a registration that has moved past it. The derivation
(`_historical_chain`) binds a historical reservation to its launch record under the **same** accepted
rule (`bind_record`: digest, identity, actor, kind, entry, slice and plan digest, target, verified
placement), requires a verified placement and the release mode, and then returns `HISTORICAL` with a
reason naming the superseded contract and ADR-0045 §7 — **never `PASSED`**; a chain that does not bind is
`UNBOUND`. A historical reservation is never reservable, executable, collectable or admissible, and its
identity stays spent.

### 2.2 Registration-historical rebinding: one exception to ADR-0052 §2.3, proven before any write

ADR-0052 §2.3 stands: a launched binding is never rebound over current evidence. **This section adds
exactly one exception**, and it applies to a bound cell only when **all** of the following are proven,
under the ledger lock, before the specification is written:

1. the cell already holds a binding in the prepared-cells record;
2. the bound identity **was launched** — a reservation beside the ledger **and** a ledger row under it
   (an unreadable store is no licence to rebind; a binding with either missing is `refused_cell_state`);
3. the bound reservation — current or historical — is integrity-valid, names the binding's identity and
   specification digest, and a launch record binds to it under the accepted rule;
4. the accepted runner derives the cell `HISTORICAL` from that evidence — any other derived state
   (`PASSED`, `PREPARED`, `LAUNCHED`, `INTERRUPTED`, `FAILED`, `REFUSED`, `INCONCLUSIVE`, `UNBOUND`,
   merely `BLOCKED`) is `refused_cell_state`, and a derived identity or digest other than the binding's
   is `refused_rebinding`;
5. the registration in force **does not name** the bound specification's target and placement — the rule
   the derivation applied, checked again independently (`refused_rebinding` when it still applies);
6. the replacement identity is a `verify-` identity **fresh everywhere**: absent from the ledger, the
   reservations (current and historical), every binding and every superseded link in the cells document,
   every launch record, every specification record (current or historical parse), and the consumed
   authorization markers (`refused_cell_state` otherwise); one identity, one cell;
7. the launch tool's own preparation admits the replacement — the active registration and the cell's
   target pass admission and the specification builds — with **no** reservation written and **no** lock
   taken by that preparation;
8. no current reservation exists under the offered identity and the store lock is held for the write.

**A `PREPARED` (unlaunched) binding is not replaceable** — it is the cell's current state, not
historical evidence — and neither is a binding under the **same** registration, whatever its state.
`refused_rebinding` (exit 15, a new closed sentence) names an integrity or registration failure of
steps 3, 5 or the identity/digest agreement of step 4; every other refusal keeps its existing code.

**Preservation is part of the write, not a courtesy.** Before the cells document is replaced, the
previous document is copied byte for byte beside the ledger as an owner-only file
`<ledger>.cells.superseded-<sha256[:16]>-<stamp>.json` (created `O_EXCL`; an existing file under the same
name must be byte-identical or the preparation refuses). The new binding carries a closed **supersession
link** — `supersedes: {identity, specification_digest, reservation_sha256, cells_document_sha256,
registration_sha256, superseded_at, prior_evidence: "HISTORICAL"}` — binding the prior identity, its
digest, the SHA-256 of its stored reservation file, the SHA-256 of the preserved cells document and the
SHA-256 of the registration in force at supersession. The prior binding, reservation, launch record,
ledger row and receipt are **never deleted, rewritten or moved**; the link is what makes the prior
evidence auditable from the current record. A link naming a non-`verify-` identity, the binding's own
identity, or a missing or malformed field is refused at parse.

**Write ordering is recoverable.** Every refusal above happens before any write. The order is then:
preserve the cells document → write the specification → write the cells document. A failure at the last
step unlinks the specification just written and re-raises, so a refused or interrupted preparation leaves
no stray specification and the preserved document stays authoritative; a failure at the second leaves the
preserved copy (byte-identical to the live document) and nothing else.

**The rule is generic.** It applies to every runtime-launch cell in the catalogue, `R2-BLD-CORROBORATION`
included, whenever its prerequisites later permit — no cell identifier, family or registration is named
by the rule. It never turns historical evidence into a current `PASSED`: the superseded binding's evidence
stays `HISTORICAL`, and the successor's `PASSED` is only ever its own launch's receipt-verified success
under the registration it was prepared against.

### 2.3 What this decision does not change

The launch tool's execution surface; the reservation, lock, ledger and record contracts; the one shared
binding rule; the strict parsers; the R-2 verdict; the permission cells; every accepted refusal; the task
images, compiled configurations, task definitions, Terraform, IAM and registration blocks. **No
deployed artifact changes** (§3).

---

## 3. Consumers reviewed together, and deployment impact

**No task entry imports the changed modules.** `launch_records`, `launch_store` and
`verification_cells` are workstation tooling: the task entrypoints' import closure
(`kalpamani.data.production.sharadar.entry` and everything it reaches) contains none of them, which a
test asserts from the module graph. The four published pagination-v2 images (`247c4383…`, `06392b61…`,
`b6b156aa…`, `ff3aa49a…`), their compiled configurations, the four ACTIVE task-definition revisions, the
launcher policies and the registration `3cf07d01…` are therefore unchanged by this decision and remain
valid; **no rebuild, republication, plan, apply or re-registration follows from it**.

The consumers that change are exactly the owner-side cell runner (`scripts/production_verification_cells.py`)
and the three modules above. The launch tool (`scripts/production_launch.py`) is **unchanged** and a test
holds it to the strict read.

---

## 4. Amendments stated

- **ADR-0052 §2.3** is amended narrowly by §2.2: a launched binding is still never rebound over current
  evidence; the one exception is a binding the runner derives `HISTORICAL` because the registration in
  force no longer names its target, proven and preserved as §2.2 states. ADR-0052's accepted text is not
  rewritten; a dated amendment section is added to it.
- **ADR-0045 §6** (the launch tool's store) is amended narrowly by §2.1: the store gains an evidence-only
  read of supported v1 reservations; its strict read, reservation, lock and ledger rules are unchanged. A
  dated amendment section is added to ADR-0045.
- **ADR-0046 §2** (the cell runner's derivation) is amended narrowly by §2.1 and §2.2: `HISTORICAL` may be
  derived from a historical reservation's bound chain, and `--prepare-cell` gains the registration-
  historical rule and the `refused_rebinding` sentence. A dated amendment section is added to ADR-0046.
- **ADR-0053 §13.5** is applied, not amended: stored evidence is versioned, parsed closed and never
  silently upgraded.

Nothing else is amended or superseded.

---

## 5. Effectiveness and execution gates

This ADR is effective on the independently reviewed merge of the pull request introducing it, together
with the offline tooling change beside it. **Acceptance authorizes nothing that runs**: reconciling the
real store, preparing any successor cell, launching any cell, attesting D-15, collecting a receipt,
taking a verdict, changing a registration, image, task definition, policy or Terraform resource, and
any AWS or provider call are each a separate written authorization. The evidence the runner will
classify `HISTORICAL` under `3cf07d01…` stays exactly what it is; no cell is `PASSED` under the new
registration until its own launch says so.
