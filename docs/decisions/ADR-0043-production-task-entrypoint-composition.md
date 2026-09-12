# ADR-0043 — Production task entrypoint composition: compiled values, task-side sources and the receipt boundary

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0043 is proposed and carries no authority.
That is a statement about the present, it will remain true of these days after any later merge, and it
is not to be rewritten as though this decision had authority before it was accepted. On merge, this ADR
becomes **ACCEPTED / IN FORCE** as **a narrow completion of ADR-0036 §2.9 and §2.12 — how the two task
entries are selected and composed offline, which values an image must compile beyond its code, how the
task refuses a non-task credential environment and an unpinned provider origin, and what its receipt
is — and nothing else**, effective together with the offline entrypoints merged beside it. **Its §3 and
§4 record proposals the owner has not decided; acceptance of this ADR decides neither.** **Acceptance
authorizes no execution** (§6).

**Nothing was run to produce this decision.** No AWS call, no ECS metadata call, no Terraform plan or
apply, no credential retrieval, no provider request, no image build. The evidence is the merged
acquisition, build, provider and pagination implementations composed on synthetic fixtures, and the
public first-party documentation of the ECS task metadata endpoint v4, the ECS container credential
provider and `sts:GetCallerIdentity`.

---

## 1. Context — what ADR-0036 left to the image, and what was still missing

ADR-0036 §2.9 fixes each task definition's `command` to the runner's entrypoint and §2.12 walks one run
from launch to cleanup; it also states that the metadata caller "is the image's entrypoint, which does
not exist in this repository". PR #95 through PR #99 merged the bootstrap, the acquisition and build
processing paths, the provider adapter and the pagination gate as offline code with **every dependency
injected**, and the bootstrap-only `run_build_task` still halts at `HALTED_PROCESSING_NOT_IMPLEMENTED`.
Nothing on `main` selects an actor, builds a real client, reads the metadata endpoint, proves an STS
identity from a real response, or turns a processing report into an exit code.

Composing those paths exposes four contracts the accepted decisions do not fix:

1. **The acquisition secret identifier.** The acquisition role may call `GetSecretValue` on exactly one
   ARN, held as a Terraform variable that is never committed; the binding's field set is closed and
   carries no secret field; the input is per-run; `KALPAMANI_*` variables are refused in a task context.
   No accepted channel delivers the identifier to the task.
2. **The compiled origin address set.** ADR-0036 §2.8 has the runner resolve the pinned provider host at
   start and refuse any address outside the set the Terraform gate materialized. No accepted channel
   delivers that set to the task.
3. **The task-side spent-identity source.** ADR-0036 §2.6 refuses an input whose run identity is spent;
   the task cannot read the workstation ledger and the acquisition actor cannot read S3 (ADR-0019). The
   merged code holds `UnavailableSpentIdentities` and refuses every input — an owner decision left open.
4. **The workstation ledger row.** §2.12 step 10 has the launch tool write the ledger row from the task's
   terminal state and counts; the launcher holds no `logs:*` permission and `DescribeTasks` reports exit
   codes only.

## 2. Decision — entry selection, composition, refusal order, receipt

```text
entries        kalpamani-production-acquire | kalpamani-research-build -- exactly one argument, equal
               to the task definition's command token; anything else refuses (REFUSED_ENTRY, exit 2)
               with nothing looked up and nothing built
import         performs no environment read, no client construction, no processing
compiled       CompiledTask (family, revision, image digest) as accepted, plus EntryConfiguration:
               acquisition -> secret_identifier, origin_addresses; build -> build_configuration;
               a configuration handing either actor the other's capability cannot be constructed
order          1 compiled configuration complete and this entry's      REFUSED_CONFIGURATION   3
               2 credential environment is a task's (names only)       REFUSED_CREDENTIAL_ENVIRONMENT 4
               3 (acquisition) origin resolves inside the compiled set REFUSED_ORIGIN          5
               4 factories called once each; a factory that raises     REFUSED_DEPENDENCY      6
               5 the accepted bootstrap, unchanged: environment, binding, input, self-check,
                 identity proof, release barrier                        bootstrap refusals     10-17
               6 the accepted processing, unchanged: reservation, credential, run, locator (acq);
                 verified inputs, Silver, Gold, manifest (build)        processing statuses    20-38
               7 an exception past processing's own reporting           UNCLASSIFIED            40
capabilities   acquisition: put-only S3, secrets client, provider adapter over the injected transport
               (one attempt, actual transport invocations counted), spent-identity registry or the
               accepted unavailable one; build: get-and-put S3, no secret, no transport, no provider
               -- its factories have no field one could arrive through (A-8)
credentials    a task holds the ECS container credential provider and nothing else: a static key, a
               profile, a shared credentials or config file or a web-identity role present BY NAME
               refuses; the container variable absent refuses; no value is ever read
metadata       one bounded read of <ECS_CONTAINER_METADATA_URI_V4>/task: scheme http, host exactly
               169.254.170.2, no userinfo, port 80 or none, a /v4/<id> path; 2 s; 64 KiB; strict
               UTF-8, no BOM, no duplicate key; documented fields only (TaskARN, Family, Revision,
               Containers[].ImageID); Cluster, when present, must agree with TaskARN; NO subnet or
               public-IP self-check (withdrawn by ADR-0036)
identity       one GetCallerIdentity through an STS client pinned to the regional endpoint, reduced to
               UserId, Account, Arn; the accepted gate compares
clients        every task client: total_max_attempts 1, standard mode, finite connect and read
               timeouts -- the accepted qualification S3 configuration, applied to SSM, STS and Secrets
               Manager too; no SDK retry can add an attempt the accounting never counted
receipt        one allowlisted sentence; the bootstrap's own sentence where one exists;
               counts_observed=true|false; integer counts as observed; cleanup_failure=<stage>:<category>
               beside the primary outcome, never in place of it; exit 0 is COMPLETED and nothing else
cleanup        the working directory is deleted before exit regardless of outcome; a failure is
               recorded as WORKING_DIRECTORY:CLEANUP_RAISED and changes neither outcome nor exit code
```

Consequences:

1. **Nothing accepted is reimplemented.** The entries call `run_production_acquisition` and
   `run_production_build`; every ceiling, ordering, count and refusal is theirs. `run_build_task` keeps its
   honest halt; it is not the build image's path.
2. **A refused entry, environment, origin, dependency, bootstrap or reservation performs zero secret and
   provider operations**, and every count reported is what the injected adapters were asked.
3. **`UNCLASSIFIED` says the counts are not a measurement.** `counts_observed=false` is the receipt's
   admission that processing raised past its own reporting; the zeros beside it are provable, not observed.

## 3. Proposed, undecided — how the compiled values reach the image

**These are proposals for the owner's decision. Nothing here is accepted by accepting this ADR.**

| Value | Proposed delivery | Alternative | What the offline code does today |
|---|---|---|---|
| acquisition secret identifier | compiled into the image at the image gate from the Terraform variable, alongside the digest and revision (ADR-0036 §2.1: expected values are constants in the image); the identifier is a name or ARN, never the secret | a new field in the acquisition runtime binding, which changes the accepted closed field set and the binding materialization | `EntryConfiguration.secret_identifier`; `None` or unusable refuses before any client |
| compiled origin address set | compiled into the image at the image gate from the set the Terraform gate materialized, refreshed by rebuilding the image before an authorized run window | delivered as a binding field, refreshed without an image rebuild | `EntryConfiguration.origin_addresses`; empty refuses; the resolver is injected |
| build configuration | compiled into the build image: accepted schemas, calendar, evidence, rule, decision sessions, as-of, commit | delivered through the build input, which changes the accepted input contract | `EntryConfiguration.build_configuration`; `None` refuses |
| task-side spent identities | a closed document the acquisition human actor materializes from the owner ledger beside the input (`kalpamani-spent-identities/v1`: sorted distinct identities, issued/expires within 24 h, SHA-256 over the list), read by the task through a fourth parameter — which **widens the task bootstrap policy** and is not done here | carrying the identities inside the acquisition input, which changes its accepted field set | `spent_source.py` states the document and its failure behaviour (every defect is `UNAVAILABLE`, never `UNSPENT`), wired to nothing; the entrypoint passes no source and the task refuses |

The compiled module the image gate would generate is named (`kalpamani_production_compiled`, one function
`entry_configuration(entry)`) and is **absent from this repository by design**; the entrypoint refuses
`REFUSED_CONFIGURATION` when it is absent, and a test asserts the absence.

## 4. Proposed, undecided — the ledger row

The task's receipt is its whole public output, on stdout, into CloudWatch. The launch tool can observe
the task's terminal state and exit codes, and can therefore record *completed / refused / uncertain* and
the closed exit code — but not the counts, which reach it only through the log stream its launcher
permission set cannot read. Completing the ledger row from the receipt therefore needs one of:
`logs:GetLogEvents` on the actor's stream for the launcher set (an IAM widening), or the owner reading the
log and completing the row by hand. **Neither is chosen here.** The offline boundary is the receipt.

## 5. Rejected alternatives

- **Select the actor from an environment variable or a flag.** A task-definition `environment` entry is
  what ADR-0036 §2.9 refuses to carry a value in, and a flag is an override surface; the command token
  already is the selection.
- **Let the SDK's default credential chain run.** A task launched on a workstation, or with an ambient
  key, would authenticate as something other than the task role and fail only at the identity gate,
  after an STS call; refusing by variable name costs nothing and reaches nothing.
- **Keep the SDK's default retry mode for SSM, STS and Secrets Manager.** The release barrier counts up
  to 60 reads, the identity proof is one call and the credential is one retrieval; hidden retries would be
  operations the accounting never counted.
- **Resolve the missing sources with defaults.** An always-`UNSPENT` registry, an empty origin set that
  admits everything, or a secret identifier read from the environment would each turn an owner decision
  into a silent default.

## 6. Effectiveness and execution gates

- **Effectiveness**: in force only on the independently reviewed merge of the pull request introducing it,
  together with the offline entrypoints beside it. §3 and §4 stay proposals until the owner decides each.
- **Execution**: acceptance authorizes no image build, no image publication, no task launch, no run, no
  AWS, metadata, STS or provider request; every ADR-0036 gate stays closed. The entrypoint has never been
  run, and no Terraform, IAM or network declaration is changed to accommodate it.
- **Scope**: nothing here amends ADR-0009, ADR-0019, ADR-0035, ADR-0036, ADR-0037, ADR-0038, ADR-0039,
  ADR-0040, ADR-0041 or ADR-0042; the exchange calendar, split-ratio semantics, action-event identity and
  R-3/R-5 stay unresolved; the durable run reservation (ADR-0038) remains the guard against identity reuse.

G2 OPEN; CONTROL DEFERRED; Phase 3 NOT COMPLETE; live trading HARD-DISABLED.
