# ADR-0040 — Research-build output objects and the build manifest: inner shapes under the accepted namespaces

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0040 is proposed and carries no authority.
That is a statement about the present, it will remain true of these days after any later merge, and it
is not to be rewritten as though this decision had authority before it was accepted. On merge, this ADR
becomes **ACCEPTED / IN FORCE** as **a narrow amendment fixing the inner object shapes the research-build
actor writes under ADR-0036's accepted `silver/`, `gold/` and `manifests/` prefixes, the manifest
contract, and the build's elapsed-time deadline — and nothing else**.

**Nothing was run to produce this decision.** No AWS call, no Terraform plan or apply, no read of any
licensed object, no provider request. The evidence is the accepted ADRs and the offline build
implementation exercised on synthetic fixtures.

---

## 1. Context — a namespace with no shape, and a deadline with no number

[ADR-0036](ADR-0036-production-data-plane-principals-and-trust-model.md) §2.3 grants the research-build
actor conditional `PutObject` under `licensed/silver/*`, `licensed/gold/*` and `licensed/manifests/*` and
exact `GetObject` on its own outputs; §2.7 requires the manifest to record the build-input digest; and
[ADR-0035](ADR-0035-initial-breakout-long-research-dataset-ingestion-design.md) §3.8 lists what a manifest's
derived `run_id` covers and states the rebuild criterion. **No accepted decision fixes the inner key shape
of an output**, the manifest's contract identifier, how a byte-identical rebuild is distinguished from a
conflict, or the elapsed-time bound the build runs under — which ADR-0018 fixes for acquisition at 1,800
seconds and no decision fixes for a build. The offline implementation merged beside this proposal had to
choose each of them; it chose the shapes below, on synthetic fakes, and this ADR proposes them rather than
leaving them as an implementation's private convention.

## 2. Decision

**Silver and Gold artifacts are content-addressed; the manifest is name-addressed by the build identity:**

```text
licensed/silver/sharadar/<dataset>/objects/sha256/<digest>          dataset  in {tickers, stocks, actions}
licensed/gold/sharadar/<artifact>/objects/sha256/<digest>           artifact in {adjusted-bars,
                                                                                universe-membership,
                                                                                corporate-actions,
                                                                                eligibility-restrictions}
licensed/manifests/sharadar/builds/<build-id>.json                  kalpamani-production-build-manifest/v1
write     one conditional PutObject each, IfNoneMatch="*", SSE-S3, full-object SHA-256 -- exactly as every
          other production object; never overwritten, never deleted by the build actor
ordering  Silver artifacts, then Gold artifacts, then the manifest LAST, only after every artifact write
          has a confirmed disposition
deadline  one actual elapsed-time deadline of 3,600 seconds over the whole build -- reads, parsing,
          computation and publication -- on an injected monotonic clock; a refused admission halts
          with the state known
```

Consequences:

1. **A 412 on a content-addressed name is `ALREADY_PRESENT`, never a conflict.** Two builds from the same
   Bronze set under the same pinned configuration produce byte-identical artifacts (ADR-0035 §3.8), and the
   second meets the first's objects by name; the disposition is recorded and nothing is read, compared or
   adopted.
2. **A 412 on the manifest name is `MANIFEST_NAME_OCCUPIED`.** A build identity is single-use; a second
   build under a spent identity stops at the manifest, publishes nothing further, and adopts nothing.
3. **The manifest binds what was consumed and produced.** It carries: the ledger digest and every payload
   and record digest the validated locators named; the compiled source-schema version and every observed
   schema digest; the Silver normalization, universe rule (with parameters), adjustment policy and
   convention, resolution policy, calendar, quality plan and evidence-set versions, the commit and the
   digest of the whole pinned configuration; the resolved profile and `as_of`; the per-dataset resolution
   and served maps; the census; the quality report; the limitation tokens; and the digest, byte count, row
   count and disposition of every output; and the adjusted-bar derivation and action-revision selection
   versions, the eligibility restrictions, and the unresolved-contract record below. Its `run_id` is
   derived from all of that **except** the build identity and the completion instant, so identical inputs
   under a pinned configuration yield an identical `run_id`.
4. **Partial and uncertain publication are preserved as exactly that.** A definitive backend refusal halts
   with the state known and no manifest; an ambiguous one halts with `publication_state_unknown` and no
   manifest; a manifest write whose outcome is ambiguous is `MANIFEST_STATE_UNKNOWN`, never success.
5. **Manifests stay LICENSED while CONTROL is deferred** (ADR-0036 §2.3). The build actor holds no CONTROL
   grant, and no CONTROL write exists.
6. **The namespaces are the accepted ones.** Every output lies inside a prefix ADR-0036 already grants for
   conditional `PutObject`; **no IAM statement, bucket-policy statement, Terraform declaration or deployed
   resource changes**, and the deletion runbook already names the prefixes.
7. **A revision is a transition in the chronology of observations, not a distinct content.** A row key's
   revisions begin whenever an observation delivers content different from the previous observation's;
   unchanged deliveries extend the current revision and are counted; a return to earlier content is a
   **new revision** current from its own observation (`A -> B -> A` selects A, B, A at the respective
   cutoffs). Content identity and the content's first sighting are recorded beside the chronology and
   never stand in for it: evidence about a content bounds the revision that first made it current, and a
   returning revision is bounded by its own observation. Every revision records its observations, so a
   document served at an earlier `as_of` carries only what was observed by then.
8. **One revision of an action is operative at a cutoff.** Before any rule consumes an action, the current
   revision of each action key is selected -- the latest admissible at that cutoff -- and superseded
   revisions of the same key are never operative beside it. Distinct keys are distinct events. The
   vendor's actions table carries **no event identity**, so a correction to a key field (date or action)
   and a separate event cannot be told apart: a key absent from a later delivery whose request window
   covered it is recorded as a **redelivery gap** on that key, never read as a deletion or a correction.
   An adjusted bar that would consume a gapped split is **withheld** and counted; a membership clause
   still consumes a gapped listing or delisting event (the exclusion is the conservative direction); the
   manifest records the unresolved contract and the counts. Resolving it needs an accepted contract for
   event identity or vendor semantics, which this ADR does not supply.
9. **Adjusted bars carry complete lineage and a derived availability.** Every adjusted row names the exact
   bar revision and every split revision it consumed (entity, dataset version, key, content digest,
   sequence, ratio) and carries **two** availabilities kept apart: `source_governing_time`, the raw bar's,
   and `derived_governing_time`, the latest governing time of every input actually consumed -- so a split
   revision or correction available later than the bar can never yield a value labelled available before
   it, and an action not consumed affects neither the value nor its availability. A verifier reconstructs
   the value and the consumed set from the recorded lineage against the served revisions. The derivation
   is versioned (`adjustment_derivation_version`) beside the action-selection policy
   (`action_selection_version`), and both are in the manifest and the `run_id`.
10. **Membership decisions are immutable; quality restrictions are a separate artifact.** A membership row
    records the decision taken at its cutoff and every fact it consumed (bars, attribute revision, action
    revisions) and is **never filtered, edited or removed by a later finding**. A security-scoped BLOCKING
    finding raised by a later observation produces an **eligibility restriction** -- security, check,
    severity, count, `restricted_from` (the earliest availability of the offending observations),
    `sessions_affected` (decision sessions whose cutoff is at or after it) and what is withheld
    (`adjusted-bars`) -- published beside the decisions in `gold-eligibility-restrictions` and listed in
    the manifest's `restrictions` and `restricted_securities`. Downstream use of a restricted security is
    prevented by the withheld artifact and the published restriction, not by rewriting history. A
    build-scoped BLOCKING finding is different: it refuses publication altogether (`REFUSED_QUALITY`).

## 3. Effectiveness and execution gates

- **Effectiveness**: this amendment is in force only on the independently reviewed merge of the pull
  request introducing it. The offline implementation that accompanies it (`build_manifest.py`,
  `build_processing.py`) writes these shapes to synthetic fakes only; that code existing is not this
  amendment being in force.
- **Prerequisite, unchanged**: the split ratio is read from the vendor `value` field as the forward
  factor; that reading is an assumption recorded beside the implementation and is not verified by this
  ADR. No build against vendor data may treat it as established.
- **Execution**: acceptance authorizes no build and no run. Every gate ADR-0036 leaves closed stays closed —
  Terraform application, R-3 and R-5 verification, image publication, task launch, the first bounded
  ingestion — and the exchange-calendar artifact the build consumes is **synthetic in this repository**: a
  real calendar is a separately reviewed configuration artifact, and no build may run against vendor data
  before it exists.
- **Scope**: nothing here amends ADR-0035's design, ADR-0036's grants, ADR-0037's Bronze layouts, ADR-0038's
  reservation, or any qualification contract.

## 4. Rejected alternatives

- **Name outputs by build identity.** A byte-identical rebuild would write duplicate objects under new names
  and the rebuild criterion could not be observed at the store.
- **Publish the manifest first.** It would name objects that do not exist and would have to be overwritten.
- **No build deadline.** An unbounded task is the thing ADR-0018 refused for acquisition; the same reasoning
  holds for a build, and a bound that is only a convention in code is a bound a later edit can lose.
- **Publish manifests to CONTROL.** CONTROL is deferred by its own decision.

G2 OPEN; CONTROL DEFERRED; Phase 3 NOT COMPLETE; live trading HARD-DISABLED.
