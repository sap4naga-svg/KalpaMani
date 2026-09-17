# `TARGET_NOT_FOUND` — consumers of `ObservedClass`, compatibility and rebuild consequences (2026-09-17)

The 2026-09-17 correction adds one member, `TARGET_NOT_FOUND`, to the closed `ObservedClass` of
`r3_verification.py` (ADR-0046's vocabulary), emitted only by the permission-subcell classifier
(`permission_cells.classify`) for ECS's exact documented answers `ClientException: TaskDefinition not found.`
and `ClusterNotFoundException`. Every consumer of the vocabulary was reviewed; this note records what each
does with the new member and what, if anything, must be rebuilt.

| consumer | how it uses `ObservedClass` | effect of the new member | action |
|---|---|---|---|
| `r3_verification.py` (`classify`, R-3 record parser, rows) | classifies S3 answers; parses recorded classes by value; decides `matched` from each row's admitted set | the R-3 classifier never emits it; no row admits it; the parser accepts it as a member (an R-3 record will never contain it) | none |
| `permission_cells.py` (`classify`, `decide`, record/attempt/cleanup contracts, derivation, matrix) | the permission classifier; the decision sets; `possibly_created` / `possibly_started` rules; settlement targets | emits it for the two documented ECS answers; `UNDECIDED` for either expectation; definitely-not-committed, so no `possibly_started`, no launch for the cleanup; the record contract refuses a document that claims a launch under it; the derivation and matrix treat it as any undecided record | corrected; 3 regressions |
| `scripts/production_permission_cells.py` (the workstation tool: execute, `--check-record`, `--cleanup`, `--recover-*`, matrix lines) | prints and reads classes by value | reads and prints the new value; `settlement_targets` sees no launch for such a record | none beyond the module change |
| `permission_probe.py` (`PermissionProbeObservation` — the task probe's receipt line, parsed on the workstation) | `ObservedClass(observed)` on the line the probe image printed | a probe image built **before** the correction can only print `AMBIGUOUS` for such an answer; the corrected workstation parser accepts both; a workstation **older** than the correction would refuse a `TARGET_NOT_FOUND` line from a **newer** image (`ValueError` → the observation is refused, not misread) | none: readers are upgraded first (this merge); images later or never (below) |
| `permission_probe_entry.py` (the probe task's entry: `issue_subcell` in the image) | classifies inside the image through `permission_cells.classify`; `NOT_EXERCISED` on early refusals | an image at `a59ad2c4` embeds the pre-correction classifier | **no rebuild required**: every `L3_TASK` / `L3_HELD_TASK` subcell targets an existing resource (S3 prefixes, the secret, SSM parameters, its own held task), so no task-side subcell can meet this answer; a rebuild would only change what such an image would print for an answer it will not receive. The two probe images at `a59ad2c4` are therefore **stale for this class only**, and that staleness is recorded, not repaired, in this cycle |
| `deletion_rehearsal.py` / `deletion_rehearsal_task.py` / `deletion_rehearsal_launch.py` (`_decide`, the rehearsal task record) | classifies through `permission_cells.classify`; decides PASS / FAIL / INCONCLUSIVE; the task record parser accepts any member | `INCONCLUSIVE` in both branches (not PASS, not FAIL) — "anything else decides nothing"; the parser accepts the member | none (the rehearsal path is closed, `deletion_rehearsal_open = false`, no rehearsal image published) |
| `verification_cells.py`, `permission_client.py` | import other names from `permission_cells`; do not enumerate the vocabulary | none | none |
| governance tests `test_adr_0046_governance.py` (every member named in ADR-0046), `test_adr_0047_governance.py`, `test_adr_0048_governance.py` | pin the vocabulary to the ADR text | ADR-0046 names the member with its meaning; ADR-0047 §3.2 and §11 explain it | updated in the same change |

**Serialization.** `ObservedClass` is a `StrEnum`; records carry the value string in canonical JSON. No
existing record contains the new value (none could: the member did not exist when they were written — the
row-34 record keeps `AMBIGUOUS`). Records written after the correction may contain it; readers **at or after**
this commit accept it, readers before it refuse the document with a closed `ValueError` (never a silent
misclassification). Schema versions and contract identifiers are unchanged: the member is an addition to a
closed vocabulary, not a shape change.

**Distinction preserved.** A target validation failure is neither a permission denial nor a success:
`TARGET_NOT_FOUND` ∈ `_UNDECIDED_CLASSES`, ∉ `_DENIAL_CLASSES`, ∉ any `_SUCCESS_CLASS`. "TaskDefinition not
found" is never counted as a denial, and never satisfies a `DENIED` expectation.

**Not decided here.** The six subcells whose §3.3 derivations name resources that do not exist by construction
(`*-RUN-OTHER-REVISION`, `*-RUN-OTHER-FAMILY`, `*-RUN-OTHER-CLUSTER`) are not re-targeted and not blocked by this
correction (ADR-0047 §11); that is a separate governance decision, and R-6 is not read as passed.
