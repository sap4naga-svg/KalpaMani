# ADR-0052 — A dedicated R-2 corroboration cell: the reachability hook rides its own launch, and a PASSED cell is never rebound

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0052 is proposed and carries no authority.
That is a statement about the present, it will remain true of these days after any later merge, and it
is not to be rewritten as though this decision had authority before it was accepted. On merge, this ADR
becomes **ACCEPTED / IN FORCE** as **one new cell in the ADR-0046 §2.3 catalogue (`R2-BLD-CORROBORATION`),
the re-attachment of ADR-0045 §12's hook to that cell alone, the rebinding refusal of §2.3 and the
evidence rules of §2.4 — and nothing else**, effective together with the offline tooling change merged
beside it. **Acceptance authorizes no execution** (§5): no launch, no path, no analysis, no receipt
collection, no reservation, no D-16 attestation, no verdict, no rerun of any PASSED cell, no permission
batch, no IAM, Terraform, tfvars, registration or image change, no acquisition.

**The condition above has since been satisfied.** **PR #126 merged** — merged **2026-09-17T18:53:23Z**, merge commit
**`01f77a10a2341b1d1d99a7fe0024b104563d692c`**, ordered parents **`d5407d8a84538827730e576240e9ec0023997671`** (the PR #125 merge,
which carried the corrected watcher request shape) then **`a489f13f277b12109af5b792c6616f7327be495d`** (the reviewed head), with a
**merge tree identical to the reviewed pull-request head tree** (`a207f4146dba274e8294f87bbe26f44b4ee9ee7f`). ADR-0052 is therefore
**ACCEPTED / IN FORCE** exactly as the clause above states — the cell of §2.1, the re-attachment of §2.2, the rebinding refusal of §2.3
and the evidence rules of §2.4, effective together with the offline tooling change merged beside it, and nothing else. While the pull
request was open it was proposed and carried no authority — true then, and not rewritten. **The owner's acceptance (2026-09-17) takes
this design as the governed execution vehicle for completing build-isolation verification and waives, weakens and marks nothing**:
R-2 still requires a successful dedicated corroboration launch, exact task/interface attribution, an analysis started inside the
accepted launch window, returned path and analysis evidence matching the accepted destination over TCP port 443,
`network_path_found = false`, an admitted explanation on a placed component, complete cleanup, the owner's later D-16 attestation and
the accepted `--verdict-cell R2-BLD-ISOLATION` step. Acceptance authorized no execution; the one execution of the prepared cell is its
own separate written authorization, and the verdict step another. **This synchronization changed no runtime behaviour, task image,
compiled configuration, Terraform, IAM or registration**, and it leaves the prepared specification (`b93d656d…`) exactly as prepared.

**Nothing was run to produce this decision.** No AWS call, no STS call, no S3 operation, no image
built or pulled, no credential retrieved, no provider request, no private input inspected. Every result
beside this text is a counting fake's, on synthetic temporary files. **Mocked results are not AWS
verification.**

---

## 1. Context

ADR-0045 §12 (accepted on the merge of PR #121) admitted the launcher's held-task `while_running` hook for
a released build verification launch and had the cell runner hand it to exactly one cell,
`R1-BLD-BOOTSTRAP`. The reviewed R-2 watcher (`reachability_hook.py`, PR #122, #124) is that hook: from the
exact task the launch tool holds, one `CreateNetworkInsightsPath`, one `StartNetworkInsightsAnalysis`,
polling, a private journal and a proposed (never attested) D-16.

On 2026-09-17 the readiness S9 build bootstrap ran **once** under that arrangement: the bootstrap
**PASSED** (`VERIFIED_BOOTSTRAP`, exit 18, receipt verified, ledger row `VERIFIED` / `RECEIPT_VERIFIED`)
and the watcher journaled `PATH_NOT_CREATED` — the service refused the path request at parameter
validation (`Client.MissingParameter`, established from CloudTrail with unique attribution) because the
request carried the deprecated bare `DestinationIp` rather than `FilterAtSource.DestinationAddress`. The
correction to the request shape is a workstation-only tooling change. **The R-1 evidence is unaffected**:
the bootstrap's PASS rests on its receipt and never on the watcher.

That leaves a corroboration problem, not a bootstrap problem. The accepted runner binds one `verify-`
identity to one cell and `R1-BLD-BOOTSTRAP` is PASSED and spent; the only way to attempt the analysis
again under ADR-0045 §12 as accepted would be to re-prepare the PASSED cell over a new identity and
launch it a second time — rebinding the cell's evidence to a second launch, and making the second
bootstrap launch the one the matrix reports. ADR-0046 §2.3's rule that state is derived and never
remembered gives no licence for that: a cell whose bound identity was launched has evidence, and evidence
is not replaced.

## 2. Decision

### 2.1 One new cell: `R2-BLD-CORROBORATION`

The ADR-0046 §2.3 catalogue gains one runtime-launch cell under R-2:

| Cell | Kind | Actor · entry | Prerequisites | Execution |
|---|---|---|---|---|
| `R2-BLD-CORROBORATION` | runtime launch | build · `kalpamani-research-build-verify` | `R3` PASSED **and** `R1-BLD-BOOTSTRAP` PASSED (current — `HISTORICAL` blocks it) | the accepted cell runner and launch tool: one fresh `verify-` identity, its own prepared specification over the **accepted empty run set** (ADR-0045 §11) with a `NORMAL` release, one authorization naming its digest, one launch, the hand-read or collected receipt |

It is **a dedicated build verification launch whose purpose is to carry the hook** — the vehicle for the
analysis, on the registered build-verification revision and image, with a matching release and the same
receipt contract as the bootstrap (`VERIFIED_BOOTSTRAP`, exit 18, one probe attempt, zero S3, secret and
provider operations). `PASSED` here is **the launch's own success and nothing more**: it is not the
isolation verdict, it establishes nothing about reachability, and a hook that created no path, started no
analysis or failed leaves this cell exactly as PASSED as a hook that did everything — the verdict cell is
where the analysis is judged.

### 2.2 The hook rides this cell alone; `R2-BLD-ISOLATION` depends on it

ADR-0045 §12's attachment point moves: the runner hands a `while_running` hook to `R2-BLD-CORROBORATION`
and to **no other cell** — not `R1-BLD-BOOTSTRAP` (which keeps its PASSED evidence exactly as recorded),
not the acquisition bootstrap, never a negative. The launch tool's admission rule (a released build
verification launch with a `verify-` identity) is unchanged; the runner's `while_running_for` is what
narrows it to the one cell.

`R2-BLD-ISOLATION` now depends on `R2-BLD-CORROBORATION` (previously on `R1-BLD-BOOTSTRAP`): the verdict is
taken on the **corroboration launch's** record and receipt — the launch whose interface the analysis was
started from — with the binding checks of ADR-0045 §3 unchanged: the analysis' source must be that
launch's own interface, its destination the smallest compiled origin address at port 443 over tcp, its
start inside `[launched_at, recorded_at]`, its result `succeeded` with no path found and an admitted
explanation on a placed component. While the corroboration cell is not PASSED the verdict cell is
`BLOCKED`; while no verdict is recorded it is `UNEXECUTED`; without owner-attested evidence it is
`INCONCLUSIVE`.

### 2.3 A launched binding is never rebound

`--prepare-cell` refuses (`refused_cell_state`) when the named cell already holds a bound identity that
was launched — a reservation beside the ledger or a ledger row under it — whatever identity is offered.
Unreadable store state is no licence to rebind. The prepared-cells record keeps the binding, the
reservation, the launch record, the receipt and the row of the PASSED R-1 cell byte for byte; the
corroboration is a new binding under a new identity, never a replacement. A spent identity offered for
the new cell is refused by the one-identity-one-cell rule already in force.

### 2.4 What may make R-2 PASSED, and what may not

The verdict tool marks `R2-BLD-ISOLATION` PASSED only from **actual returned evidence** — a
`NetworkInsightsPath` and a `NetworkInsightsAnalysis` the service returned, transcribed into the
`kalpamani-reachability-evidence/v1` document by the owner (D-16, owner-attested) — bound to the
corroboration launch. The watcher's journal and its proposed document are inputs to the owner's
transcription and carry `evidence_is_owner_attested: false`; they are never the verdict's input.
Evidence that is missing, an analysis that failed or did not run, a source that is not the corroboration
task's interface, a destination, port or protocol that is not the compiled one, a start outside the
launch window, an analysis that found a path, an explanation on a component outside the placement, or a
cleanup that is incomplete gives `INCONCLUSIVE` or the closed failure and never a pass; a later
corroboration resolves only the insufficiencies ADR-0045 §3 names resolvable, and a contradiction reads
`UNBOUND`.

## 3. Consumers reviewed together

The catalogue and matrix (`verification_cells.py`: one definition inserted, one dependency moved, the
enumeration and derivation unchanged); the specification builder and parser (unchanged — the cell uses
the accepted empty run set); the reservation store (unchanged); cell preparation and execution
(`production_verification_cells.py`: `HOOK_CELL_ID`, `_identity_launched`, the prepare refusal); hook
admission (the launch tool and launcher unchanged); receipt collection and completion (unchanged — the
same receipt contract, the same collector); D-16 parsing and the verdict (unchanged rule, taken on the
corroboration record); recovery and cleanup (unchanged — the watcher's tag-filtered cleanup and the launch
tool's recovery own their own objects). **Production build behaviour is unchanged**: no task entry, image,
compiled configuration, registration, IAM, Terraform or tfvars value moves.

Held by regressions in `test_production_verification_cells.py`: the catalogue names the cell with its
prerequisites and the verdict's dependency; the runner hands the hook to this cell alone; the whole
lifecycle on fakes — the bootstrap PASSED, re-preparing it refused with its binding, row, reservation and
record unchanged, its spent identity refused for the new cell, the corroboration prepared, launched with
the hook invoked exactly once on the held `RUNNING` task at the registered revision and image, completed
from its own receipt (the bootstrap's receipt and a receipt claiming a data-plane operation refused), the
verdict INCONCLUSIVE without evidence and on mis-attributed, out-of-window or wrong-destination evidence,
a found path refused as the unresolvable contradiction, and PASSED only from evidence bound to the
corroboration's own interface, window and destination; and `test_adr_0046_governance.py` requires the
cell in ADR-0046's text.

## 4. Amendments stated

**ADR-0045 §12 is narrowly amended** (its §13): the hook's attachment point is `R2-BLD-CORROBORATION`,
not `R1-BLD-BOOTSTRAP`; the admission rule and everything else in §12 stand. **ADR-0046 §2.3 is narrowly
amended** (its §7): the catalogue gains the row of §2.1, `R2-BLD-ISOLATION` depends on the new cell, and
the prepare refusal of §2.3 joins the runner's rules. No other accepted document changes; the six PASSED
R-1 cells, R3, their records and every launch record stay what they are.

## 5. Effectiveness and execution gates

Acceptance authorizes **no** execution: no launch of the new cell, no path, no analysis, no receipt
collection, no reservation, no D-16 attestation, no R-2 verdict, no rerun of any PASSED cell, no
permission batch, no IAM, Terraform, tfvars, registration or image change, no acquisition, dataset or
backtest. Preparing the cell (offline, no client) and executing it are each their own written
authorization (D-15 and the single-launch S9 authorization for its fresh identity); the D-16 transcription
is the owner's; the verdict command runs only after it. **G2 stays OPEN, CONTROL stays DEFERRED, Phase 3
stays NOT COMPLETE, live trading stays HARD-DISABLED.**
