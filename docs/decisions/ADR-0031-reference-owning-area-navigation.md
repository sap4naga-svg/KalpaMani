# ADR-0031 — Owning-area navigation for a disclosed reference

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0031 is proposed and carries no authority,
and so are the deltas it makes to the Cockpit specifications in the same pull request. That is a
statement about the present, it will remain true of these days after any later merge, and it is not
to be rewritten as though this decision had authority before it was accepted. On merge, this ADR
becomes **ACCEPTED / IN FORCE** as **architecture, contracts and governance** — and nothing else.

**The acceptance event is exact:** the independent review and merge of **pull request #80**,
the pull request introducing this ADR, into `main`. No merge SHA and no merge timestamp is predicted here; those are repository
state, recorded after the fact if they are recorded at all.

**Date:** 2026-09-07
**Supersedes:** nothing
**Superseded by:** —
**Amends:** [ADR-0030](ADR-0030-cockpit-reference-resolution-and-unavailable-targets.md) at **R10
only**, and [`docs/cockpit/read-model-contracts.md`](../cockpit/read-model-contracts.md) at §4.2,
§4.3.1, the new §4.3.2 and two §4.5 payload notes. **It amends no other rule of ADR-0030**, whose
R1–R9 and R4.1 are untouched, and **it does not amend, supersede or edit ADR-0026, ADR-0027,
ADR-0028 or ADR-0029**, each of which remains **ACCEPTED / IN FORCE**.
**Relates to:** [ADR-0027](ADR-0027-cockpit-and-feedback-architecture-and-governance.md),
[ADR-0028](ADR-0028-cockpit-contract-completion-and-boundary-corrections.md),
[ADR-0029](ADR-0029-valid-zero-values-and-cache-freshness-deadlines.md)

**Nothing was run to produce this decision.** No AWS, STS, SSO, IAM, Secrets Manager or S3 call; no
Terraform command of any kind; no Terraform state, backend configuration, `.tfvars` or `.terraform/`
read; no `.runtime/` inspection; no provider request; no credential access; no Run A retry, Run B or
combined assessment; no P1–P9 execution; no backtest; and no broker, LEAN or IBKR activity. **No
Blueprint PDF was opened or edited.** No dependency was installed, no package manifest was changed,
and no runtime behaviour was implemented. This decision is authored from tracked repository
authority alone.

**No alpha is claimed anywhere in this decision.**

---

## 1. Context — the conflict, and why it is architectural

**ADR-0030 is ACCEPTED / IN FORCE**, and enforcing it removes a user-visible affordance the accepted
C4 acceptance criteria require. That is the whole problem, and both halves of it are correct.

Four accepted clauses meet, and no implementation can satisfy all four at once:

```text
1  read-model-contracts.md 4.5 declares AttentionItem.evidence_refs
       "required, kind evidence or source_fact"  -- a stated SET of exactly two kinds
2  ADR-0030 R10 keys the navigation allowlist by RefKind, and an unmapped kind
       yields NO LINK, "never a guess"
3  the traceability matrix requires of area 28 that "every item shows what happened,
       why it matters, impact, EVIDENCE and a permitted governance action", and the
       ui-ux-specification section 3 drill-down path is
       "Attention item -> its evidence -> the record that produced it"
4  4.3 gives `evidence` no catalogued destination -- it resolves by AUTHORIZED_READ to
       "a classified evidence artefact", 5 catalogues no evidence endpoint, and a Ref
       has no field in which the "scope named on the reference" can be named
```

**Before enforcement, the application obtained per-area links by mislabelling the kind.** The
attention and What-Changed producers emitted `data_quality`, `health_transition`, `reconciliation`,
`incident` and `alert` on a field §4.5 permits only `evidence` and `source_fact` on, and two
duplicated destination literals keyed those spellings to `/system/data-quality`, `/strategy/health`,
`/execution/reconciliation`, `/system/operations` and `/system/alerts`.

**Correcting the producer is right, and it is what costs the affordance.** Once every attention
reference is a conformant `source_fact` or `evidence`, R10 has exactly one route for the whole
screen — `source_fact` to `/governance/audit` — so a data-quality finding, a strategy-health
transition, a reconciliation break and a borrow record all offer one link, to the Audit Trail. **An
Audit page does not own every fact**, and a screen that says it does is worse than one that says
nothing.

**A kind cannot carry this, and that is the architectural finding.** `RefKind` answers *what is this
a reference to*. The lost links answered *which area is responsible for the disclosed item*. Those
are different questions about the same reference, and expressing the second through the first is
what produced the non-conformant output in the first place. **A second question needs a second
attribute, not a second meaning for the first one.**

---

## 2. Decision

Six rules, A1–A6. The field table, the route table and the presentation cases live in
[`read-model-contracts.md`](../cockpit/read-model-contracts.md) §4.3.2, which is where an
implementation reads them; this section states what is decided and why.

### A1 — the association is a field INSIDE the reference

**`Ref` gains one optional field, `owning_area`**, carrying one member of the closed `OwningArea`
vocabulary or nothing at all. `Ref` is already the reusable defined type every reference-valued
field is built from (§4.2), so the metadata lands on **every** disclosed reference — attention,
What-Changed and every later host field — without a second container, a parallel list or a per-model
duplicate.

**Association is by containment, and by nothing else.** The reference an `owning_area` describes is
the object it is a field of.

```text
REFUSED   association by array position -- items[i] paired against areas[i]
REFUSED   association by display text, label or title
REFUSED   association by an identifier prefix, a naming convention or a guessed shape
REFUSED   association by a runtime filesystem, module or route search
```

Each of those was available and each is refused for the same reason: **an association a reader
cannot see in the payload is an association a producer can silently get wrong**, and a positional
pairing breaks the instant a list is filtered, truncated or reordered — all of which §4.3.1 already
requires a `RefList` to survive.

**Multiplicity is at most one.** A reference names one target record, and the area responsible for
that record is one area. Where accepted authority does not determine a single owning area, the
reference **declares none** — never a list, never a first-of, never a nearest match.

**Two references in one item keep their own areas**, because each carries its own field. That is the
property the lost affordance needed and the one a per-item or per-list attribute could not provide.

**Duplicate handling.** Two references in one list may declare the same `owning_area`; they are two
references, they are not collapsed, and the shared area is not deduplicated away. Two references
that share a `ref_id` **and** a `ref_kind` while **declaring different** `owning_area` values are a
producer contradiction and are **refused at admission** — one record cannot be owned by two areas at
once, and admitting it would leave a renderer to choose.

**The comparison scope is the ADMISSION UNIT — one response payload — and not one `RefList`.** The
harm the rule names is a renderer choosing between two areas for one record, and that harm does not
arrive only inside a single list: the same record can appear in two different `RefList` fields, or
in a scalar `Ref` beside a list, and one response would then draw two different area controls for
one record. **Scoping the check to a list would state a rule narrower than its own reason.**

**That scope is also exactly as wide as the comparison is sound.** ADR-0030 R8 requires the
**environment to match the resolving envelope always**, and §4.2 gives `Ref` **no provenance
field**, so a reference cannot itself label a differing provenance and an unlabelled
differing-provenance target is refused under R8. Within one response, therefore, a matched `ref_id`
**and** `ref_kind` name **one target**. Nothing here widens that to a cross-response or global
identity claim, and **no new identity model is introduced** — the comparison is R8's, read at the
scope R8 already fixes.

**Absence is not a conflicting value.** A reference declaring an area beside one declaring none is
**not** a contradiction: `ABSENT` states nothing (A4), so there is nothing for it to disagree with,
and the declared area stands. **Only two declared and different members conflict** — reading an
absence as a conflict would refuse conformant payloads at admission, which is the opposite of the
failure this rule exists to catch.

**Validation.** `owning_area` is validated exactly as `ref_kind` and `resolution` already are: a
value outside the closed set is **refused at admission**, never rendered, never coerced and never
mapped to a nearest member.

**The semantic kind does not move.** `AttentionItem.evidence_refs` and
`WhatChangedEntry.evidence_refs` keep the kinds §4.5 declares for them, and a producer may **never**
change a reference's `ref_kind` to obtain a link. **That is the defect this decision exists to make
unnecessary**, and re-introducing it would be a violation of ADR-0030 R2 rather than a use of this
one.

### A2 — a closed `OwningArea` vocabulary, each member bound to one internal route

**Seven members**, each naming one Cockpit V1 area, each mapped to exactly one internal route. The
set is bounded by the cases that actually arise: six recover a destination the accepted C4 behaviour
offered, and the seventh resolves the borrow case from repository authority.

The normative table — member, area number, route, and the authority each is read from — is
[`read-model-contracts.md`](../cockpit/read-model-contracts.md) §4.3.2. It is stated once, there, so
that a governance test parses one table rather than agreeing with a copy of it.

**The borrow case is resolved explicitly.** The short-side attention item references a **borrow
record**, and the traceability matrix gives area 13, the Short-Side Dashboard, as the area whose
acceptance criterion is *"borrow availability is never inferred from price; unknown borrow renders
as unknown or `BLOCKED_BORROW`"*, over a `ShortSideSnapshot` served by `GET /api/v1/risk/short-side`
at the route `/risk/short-side`. **`SHORT_SIDE` is therefore its owning area**, and it is not
`AUDIT_TRAIL`, which is where the corrected producer's only available link points today.

**`AUDIT_TRAIL` is a member and is never a default.** It is declared when the reference names a
recorded `AuditEvent` — the one read model the traceability matrix gives area 26. **A governance
record is not one**: the matrix gives `GovernancePacket` and `DecisionRecord` to area 19,
`QualificationStatus` to area 24 and `MaturityStatus` to area 25, so a reference naming one
**declares no owning area** rather than this member. **An absent, unknown or undetermined owning
area never resolves to it**, and no rule anywhere may use it as a fallback. *An Audit page owns
every fact* is precisely the false claim the corrected producer currently makes on five items out of
five.

**No area value is added because a route exists.** The navigation registry carries far more routes
than seven; a route is not evidence that an area owns a disclosed reference class, and members are
added by amending this decision rather than by an implementer noticing a spare page.

**Route templates are area landing pages only.** No `OwningArea` route carries an entity segment, so
nothing is interpolated into one and there is no identifier to encode. Contextual **entity**
navigation is not required by any case this decision addresses, and it is deliberately not
introduced. A free-form URL, an absolute URL, an external origin, a producer-supplied template and a
destination derived from free text, a label or a title are each **refused**, exactly as under R10.

### A3 — ADR-0030 R10 is narrowly amended to permit a SECOND closed navigation attribute

**R10's rule is preserved and re-scoped rather than relaxed.** As written, R10 governs *"a
navigation destination for a reference"* and keys it by `RefKind`. Read literally it forbids the
destination A1 introduces, so **a new field alone would be insufficient** — the field would exist
and no rule would permit its use.

R10 is amended so that the Cockpit has **exactly two** navigation attributes for a reference, both
closed, both internal, and **kept apart**:

| | keyed by | answers | when it is used |
|---|---|---|---|
| **target navigation** — R10, unchanged | `RefKind` | *open the referenced record* | a kind the R10 allowlist maps |
| **owning-area navigation** — new | `Ref.owning_area` | *go to the area responsible for this item* | a reference that declares one |

**Neither is a fallback for the other.** An unmapped `RefKind` still yields **no target link** —
R10's *"never a guess"* is unchanged, and an owning area does not substitute for it. An absent
`owning_area` yields **no area link**, and the R10 allowlist does not supply one. A reference may
offer both affordances, one, or neither, and the two are rendered as **distinct controls that are
never merged**.

**The labels differ, and the difference is the rule.** Target navigation names the **record** —
*Trade*, *Candidate* — and reads as opening it. **Owning-area navigation names the AREA and says
so** — *"Data quality area"* — and **may never be phrased as resolving, opening, retrieving, viewing
or showing the reference, the evidence or the artefact.** A control labelled *"View evidence"* that
lands on an area page has told the reader it retrieved something it did not.

### A4 — availability and honest presentation

**Four states, kept apart**, with their exact renderings in §4.3.2:

```text
DECLARED    a closed member -- the area affordance renders, labelled as AREA navigation,
            and carries the destination's own implementation status
ABSENT      no area affordance renders. The reference states no owning area, and that is
            NOT a claim that no area owns it
WITHHELD    indistinguishable from ABSENT at the reference, because a Ref carries no
            availability and no reason (4.3.1). The contract says so out loud, so no
            renderer may report "no owning area exists"
INVALID     outside the closed set -- REFUSED AT ADMISSION, never rendered, never coerced
```

**No owning area is ever invented to satisfy a link assertion.** A test, a fixture or a screen that
requires every reference to be navigable is asserting something about the data, and the honest
answer where the data does not say is a stated absence.

**A known area whose screen is not yet built stays visibly not yet implemented.** Six of the seven
routes are placeholders in the navigation registry today. The affordance renders with that status
attached, and **navigating asserts nothing about whether the producing subsystem exists** — the
producers behind data quality, strategy health, reconciliation, alerts, operations and the audit
trail are each **NOT IMPLEMENTED**, and an area link does not make one exist.

**Reference status and area navigability are separate axes and are displayed separately.** A
reference's `resolution`, its `classification`, and every §4.3.1 unavailable outcome are unchanged
and are shown as they are today. An `UNRESOLVABLE_V1` reference may carry a navigable owning area; a
resolvable one may carry none. **Neither fact is evidence about the other.**

**Evidence-kind filters are unchanged.** They are computed from the **declared** `ref_kind`
vocabulary of the host field — for both `evidence_refs` fields, `evidence` and `source_fact` — and a
category selecting zero rows is a **true "none of these"** rather than a missing control.
**`owning_area` is not folded into that filter and does not become a kind.** An area facet may be
offered beside it and is never conflated with it.

**Navigation metadata is not evidence about anything else.** It is not completeness, not freshness,
not materiality, not severity, not ranking input, and **not authorization**. A reference does not
become more complete, more recent or more material by naming an area.

### A5 — the access boundary, and the limitation this decision does NOT repair

**`owning_area` is descriptive metadata. It is not an access grant**, and it is exactly as
non-authorizing as `Ref.classification` already is under R10.

```text
an area link does NOT authorize retrieval of the referenced artefact
an area link does NOT reveal a withheld identifier, key, locator or vendor value
an area link does NOT bypass the destination's own scope and classification checks
an area link does NOT convert AUTHORIZED_READ into a read the caller may perform
a caller denied the artefact may still see the area link, and is still denied
```

**Every ADR-0030 rule this touches is preserved.** R8 identity comparison, the tombstone rule, the
provenance rules, the five §4.3.1 unavailable outcomes, `REFERENT_NOT_FOUND`'s two landing places,
the scope-denial-versus-classification-withholding separation, the permitted resolution sets and the
R7 cardinality quantities are **unchanged**. **No evidence endpoint is manufactured**, no kind is
remapped to `audit_event`, and `evidence` is **not** given a destination by mapping it to the Audit
Trail.

**The general evidence-retrieval limitation stays OPEN, and this decision names it rather than
implying it is fixed.** Two accepted gaps survive untouched:

```text
UNRESOLVED   4.3 resolves `evidence` by AUTHORIZED_READ to "a classified evidence artefact",
             and 5 catalogues NO evidence endpoint -- so there is no general destination
             at which an evidence artefact can be retrieved
UNRESOLVED   4.3 says the scope is "named on the reference", and 4.2 gives Ref no field in
             which to name one -- so a reference-carried scope is not expressible
```

**Working area links are not a repair of either.** A reader who reaches the Data Quality area has
navigated; they have not retrieved the artefact, and nothing here claims they have. Closing those
two gaps is a separate decision, and it is not opened by this one.

### A6 — compatibility, and the integration decision the implementation must make

**This is assessed as a contract change, not as fixture byte equality.** What moves:

| Change | Direction | Effect on a consumer |
|---|---|---|
| `Ref` gains optional `owning_area` | **widening** of what a producer may emit | a consumer that ignores unknown keys is unaffected; **a consumer validating `Ref` as a closed object shape rejects it, and one that strips unknown keys silently drops the metadata** |
| `OwningArea` added as a closed vocabulary | **addition** | nothing consumes it until a producer emits one |
| R10 amended to permit a second attribute | **widening** of permitted navigation | none; no existing destination changes |
| `evidence_refs` kinds, resolutions and cardinality | **unchanged** | none |
| any `schema_version` value | **unchanged by this decision** | — |

**Affected payloads and validators.** `Ref` is a §4.2 reusable defined type, so the shape change
reaches **every** payload carrying a reference, and every validator, factory and shared type built
over it — including the nineteen models whose `schema_version` the pending reference-enforcement
work already moves. **Shared types are shared blast radius**, and that is the whole reason this is
stated as an integration decision rather than as a number.

**The four §6.1 deployment constraints are NOT assumed, and the old no-bump exception is not
inherited.** ADR-0030 §6.1 records four conditions and states that its reasoning **expires** the
moment any one stops holding. **A later implementation must re-check all four against the tree it
lands in, and bump rather than proceed if any has changed.** Re-stating them here as though they
still hold would be exactly the unproven deployment assumption §6.1 warns against.

**The pending all-nineteen-model `v2` change is accounted for and is NOT treated as merged
authority.** An open, unmerged pull request moves nineteen `schema_version` constants from `v1` to
`v2`. **While it is open it carries no authority**, this decision neither ratifies nor blocks it,
and **no version value is predicted here**. What is decided is the **rule the later implementation
must follow**:

```text
the implementation MUST determine, from the tree it actually lands in, whether the
    owning_area shape change ships INSIDE the same coordinated atomic replacement as the
    pending enforcement change, or AFTER it
INSIDE   the two changes are ONE replacement and the affected models carry ONE version
         identity for the combined change. It is refused to ship one half as v2 and the
         other as v3 within a single atomic replacement, and refused to let an already
         published v2 silently acquire a second meaning
AFTER    the pending change has landed and been deployed, so the coordinated replacement
         is spent -- the four constraints are re-checked from scratch and the shape change
         carries its own bump
REFUSED  deciding the version by reading this document instead of the tree, and
         REFUSED asserting a version number in this decision at all
```

**The section numbering collides with the same pending pull request, and the collision is resolved
here rather than discovered during a merge.** Both changes insert a subsection at the same anchor —
immediately after §4.3.1's navigation rule. This decision takes **§4.3.2**, contiguous with the
accepted §4.3.1 and at the **same `####` heading level**, so accepted `main` never carries a gap or
a dangling number if the pending work does not land.

```text
THIS DECISION      4.3.2  Owning-area navigation
ON INTEGRATION     4.3.3  The authorized carriers, and what each one's identity is
                   4.3.4  The scope a resolution requires, and where it comes from
REQUIRED           every clause of BOTH rule sets is preserved verbatim, and every
                   cross-reference to a renumbered section is updated with it
REFUSED            dropping, merging, abridging or deferring either rule set to resolve
                   the collision. A mechanical numbering conflict is an INTEGRATION TASK,
                   and it is never permission to discard a rule
REFUSED            renumbering the pending work in THIS pull request -- it is open,
                   unmerged and NOT EDITED here
```

**The two rule sets do not compete on substance, and that is checkable rather than assumed.** The
pending sections govern **which host fields may carry an `EMBEDDED` target and how a carrier's
identity is compared**, and **which scope a resolution requires and where that scope is read from**.
Neither names a navigation destination, and neither adds a field to `Ref` — so **A5's two open
limitations survive the integration unchanged**: the pending scope section derives the **caller's**
required scope from the accepted contract, and does **not** give `Ref` a field in which a
reference-carried scope could be named.

---

## 3. Alternatives considered

| Alternative | Why not |
|---|---|
| **Withdraw per-area navigation and accept one Audit link** | it asserts that the Audit Trail owns a data-quality finding, a health transition, a reconciliation break and a borrow record. A wrong destination is worse than none, and the C4 drill-down path requires one |
| **Widen `AttentionItem.evidence_refs` to admit `data_quality`, `health_transition`, `reconciliation`, `incident` and `alert`** | it re-legalises the mislabelling ADR-0030 R2 corrected. Those kinds answer *what is this a reference to*, and none of these references is a reference to a `DataQuality` record — it is a reference to the recorded fact the projection was built from |
| **Map `evidence` and `source_fact` to a destination in the R10 table** | one route for two kinds carried by every projection is the single-Audit-link outcome under a different name, and it makes the false claim structural instead of incidental |
| **A parallel `owning_areas` array on `RefList`, paired by index** | positional association, explicitly refused by A1. It breaks under filtering, truncation and reordering — all of which §4.3.1 requires a `RefList` to survive — and it cannot describe a scalar `Ref` at all |
| **A per-item `owning_area` on `AttentionItem`** | an item is *"derived from alerts, health, risk, data quality and governance"*, so one item legitimately carries references from different areas. A per-item attribute destroys exactly the distinction the affordance exists to show |
| **Derive the area from the `ref_id` prefix** | `demo-evidence-data-quality` looks derivable and is a fixture naming habit, not a contract. `SafeId` constrains characters, never meaning, and a producer that renamed an identifier would silently move a link |
| **Derive the area at render time by searching the route registry** | a runtime search over module or route state is a resolver by another name, and it produces a destination nobody declared. R10 refuses generic resolvers for this reason |
| **Give `evidence` a real endpoint and resolve the reference properly** | that is the right long-term repair and it is a much larger decision — an evidence retrieval surface, a reference-carried scope, and a classification gate. A5 names it as unresolved rather than half-building it here |
| **Reuse `Ref.classification` to select a destination** | classification labels sensitivity, not ownership. Two areas share a classification, and one area spans several |
| **Let a producer supply the route** | a producer-supplied route template is a free-form URL with extra steps, and R10 refuses it for that reason |
| **Add every area in the navigation registry as a vocabulary member** | members would then exist that no reference class justifies, and the first implementer wanting a link would pick the nearest one. The set is bounded by the cases, and is amended when a case appears |

---

## 4. What this decision does not do

```text
Cockpit runtime behaviour changed by this decision:               NONE
new src/ or apps/cockpit/src/ modules created:                    NONE
routes, fixtures or dependencies added:                           NONE
schema_version values changed by this decision:                   NONE
the pending reference-enforcement pull request:                   NOT EDITED / NOT MERGED
a general evidence retrieval endpoint:                            NOT CREATED / STILL OPEN
a reference-carried scope expression:                             NOT CREATED / STILL OPEN
Brain, scanner, strategy, risk, portfolio and execution engines:  NOT IMPLEMENTED / NOT AUTHORIZED
production read services, projections, databases, schedulers:     NOT AUTHORIZED
C7 research and feedback interfaces:                              NOT STARTED
C5 completion follow-up:                                          STILL PENDING / NOT AUTHORIZED
dependency or manifest changes:                                   NONE
Blueprint PDF changes:                                            NONE
provider data used:                                               NONE
private artifacts read:                                           NONE
AWS / Terraform operations:                                       NONE
broker, LEAN and IBKR activity:                                   NONE
Run A retry:                                                      NOT AUTHORIZED / NOT RUN
Run B:                                                            NOT AUTHORIZED / NOT RUN
combined assessment:                                              NOT AUTHORIZED / NOT RUN
P1-P9:                                                            UNEVALUATED
G1 / G2:                                                          OPEN / OPEN
provider selected:                                                NONE
backtesting:                                                      NOT STARTED
Phase 3:                                                          NOT COMPLETE
ADR-0005:                                                         PROPOSED
INC-0002:                                                         OPEN
CONTROL:                                                          DEFERRED
live trading:                                                     HARD-DISABLED
```

**ADR-0026, ADR-0027, ADR-0028 and ADR-0029 remain ACCEPTED / IN FORCE**, none of their documents is
edited by this decision, **ADR-0030 remains ACCEPTED / IN FORCE and is amended at R10 only**, and
**no gate is closed by it**.

---

## 5. The bounded implementation follow-up

**This decision implements no runtime behaviour, and none is authorized by it.** The pull request
introducing it changes specification text and governance tests only; no module under `src/`, no
module under `apps/cockpit/src/`, no fixture, no route and no dependency is changed by it.

On acceptance, **one bounded implementation cycle** — carried by the pending reference-enforcement
work rather than opened here — would:

```text
determine the combined schema_version decision from the tree, under A6, and re-check the
    four 6.1 deployment constraints before landing anything
add owning_area to the Ref type as an optional closed member, refusing any other value at
    admission, and refusing a same-ref_id-and-kind pair that declares different areas
compile the OwningArea route table from 4.3.2 as ONE closed allowlist in ONE module
validate on the actual admission and render path, not only in a table test
restore per-area links on attention and What-Changed WITHOUT changing any evidence kind
render the area affordance with an AREA label, distinct from a target-navigation label,
    and carrying the destination route's own implemented or placeholder status
keep reference resolution, reference status and access enforcement independent of it
replace the known-narrowing regression -- the evidence-kind filter case that once narrowed
    to one item and now narrows to zero or four -- with positive AND negative behavioural
    tests over owning-area navigation
complete a fresh independent review before any merge
```

**It is a separate authorization**, and it is not opened by merging this decision.
**Specification, implementation, research, deployment and execution stay five separate gates.**
