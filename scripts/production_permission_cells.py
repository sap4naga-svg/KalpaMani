"""The R-4 .. R-9 permission-subcell tool (ADR-0036 s.3; ADR-0047; ADR-0048).

**Refuses by default.**

The default invocation prints the plan of one subcell, or of every subcell of one cell,
and performs nothing. ``--check-record`` reads one permission record back through its
contract. ``--prepare-subcell <id>`` admits the bindings, resolves the subcell's exact
target for one session stamp, binds the prerequisite objects it reads to the exact records
that created them, and writes the **statement** (``kalpamani-permission-statement/v1``)
whose digest the owner's authorization names -- no identity proof, no client, nothing
performed. The authorized branch (``--execute-subcell <id> --authorization <file>`` with
``--i-am-the-owner-authorizing-one-permission-subcell``) executes **one** L3 subcell:
one operation by one principal against the one target the statement names, one transport
attempt, under that principal's own workstation profile and only after its identity is
proven -- and the cleanup branch (``--cleanup`` with
``--i-am-the-owner-authorizing-permission-cleanup``) settles, under the control principal,
every object a record created or may have created and every task a launching attempt
started or may have started, and confirms each absent or STOPPED.

Order of the authorized branch: automation refused → the flag → the subcell exists and is
an L3 runtime subcell → ``AWS_PROFILE`` pinned to the subcell principal's profile → the
principal's identity proven (a production human or launcher through the accepted human
bootstrap against its private binding; a qualification actor through the accepted
ADR-0021 gate; the control principal through the foundation gate) → the environment
binding, the launch-inputs registration, the private targets file and, when the subcell
needs the production secret's name, the acquisition configuration → the binding digests →
the statement recomputed from the prepared stamp and held equal to the prepared one (a
changed target, targets document, declaration, registration or prerequisite refuses) →
the authorization admitted for exactly that statement, valid now → **the authorization
consumed durably beside the ledger** (a second execution under it -- repeated, after an
interruption, from another records directory -- refuses) → the attempt record written
**before** the operation, naming the authorization, the statement and the exact object it
may create → the client built **only now**, one attempt, finite timeouts → the operation →
the record, naming the attempt it answers. An unexpected launch is stopped at once and
recorded; an answer that leaves a write or a launch open is recorded as possibly committed.
Every record is written exclusively under the owner's records directory beside the launch
records, where the cell runner derives the matrix from them.

**A task-role subcell is executed by a probe launch** (ADR-0048). The same order to
the attempt record; then, instead of a client, the accepted launch sequence under the actor's
human and launcher profiles (both identities proven through the accepted bootstrap, as the
launch tool proves them): the probe input -- the subcell, the statement and attempt digests,
the stamp and the exact resolved target -- materialized create-only, one ``RunTask`` of the
registered permission-probe revision tagged with the session's ``startedBy``, placement
verified, the release written, the task observed to its terminal state, the prescribed
cleanup, and a launch record plus an owner-ledger row written under the ledger lock. The
subcell is then **AWAITING_RECEIPT**: ``--complete-subcell <id> --receipt-lines <file>``
verifies the hand-read receipt against that launch record (the accepted receipt validator)
and, from its permission block, writes the record -- ``identity_verified`` exactly when the
probe's bootstrap released, which is the task's own identity proof. The launcher's
``ExecuteCommand`` subcell launches a **held** probe and makes its one refusal check while
the task runs; its record is written at once, and the held task is a started task the
cleanup confirms STOPPED. The probe task itself is discovered by the session's tag and
settled by the cleanup like any launched task.

No AWS activity happens in this repository's tests; every result here is a counting
fake's. **Mocked results are not AWS verification.**
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

REPO_ROOT: Final = Path(__file__).resolve().parents[1]
for _entry in (REPO_ROOT / "src", REPO_ROOT / "scripts"):
    if str(_entry) not in sys.path:  # pragma: no cover - import bootstrap
        sys.path.insert(0, str(_entry))

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex  # noqa: E402
from kalpamani.data.production.sharadar import permission_cells as pc  # noqa: E402
from kalpamani.data.production.sharadar import permission_probe as pp  # noqa: E402
from kalpamani.data.production.sharadar import r3_verification as r3  # noqa: E402
from kalpamani.data.production.sharadar.permission_client import (  # noqa: E402
    SdkPermissionClient,
)
from kalpamani.data.production.sharadar.vocabulary import (  # noqa: E402
    EXPECTED_PARTITION,
    EXPECTED_REGION,
    IdentityPath,
    ProductionActor,
)
from kalpamani.data.qualify.sharadar.runtime_binding import (  # noqa: E402
    ENVIRONMENT_BINDING_ENV_VAR,
    QualificationEnvironmentBinding,
)

AUTHORIZATION_FLAG: Final = "--i-am-the-owner-authorizing-one-permission-subcell"
CLEANUP_FLAG: Final = "--i-am-the-owner-authorizing-permission-cleanup"
#: One bounded receipt collection from a probe launch's own log stream (ADR-0049
#: s.2): a logs read under the actor's launcher profile after that identity is proven.
COLLECT_FLAG: Final = "--i-am-the-owner-authorizing-receipt-collection"
#: The consumption namespace beside the ledger (:meth:`LaunchStore.consume`).
CONSUMPTION_KIND: Final = "permission_authorization"
TARGETS_ENV_VAR: Final = "KALPAMANI_PRODUCTION_PERMISSION_TARGETS_FILE"
DECLARATION_DIR: Final = REPO_ROOT / "infra" / "aws" / "research-data-plane"
CONNECT_TIMEOUT_SECONDS: Final = 10
READ_TIMEOUT_SECONDS: Final = 30
#: Cleanup budget: two operations per key, for at most this many keys in one pass.
CLEANUP_MAX_KEYS: Final = 64
#: And at most this many launching attempts settled in one pass.
CLEANUP_MAX_LAUNCHES: Final = 8
#: How long a held probe task waits for the launcher's ExecuteCommand check (proposed
#: ADR-0048): the launcher makes its one check as soon as the release is written, so the
#: hold only has to outlast placement verification and the release; bounded by the
#: probe's own ceiling and by the launcher's observation ceiling.
PROBE_HOLD_SECONDS: Final = 180

REFUSED_OPTIONS: Final[dict[str, str]] = {
    "--all": "one subcell per authorized invocation; there is no batch",
    "--retry": "a subcell is never retried; an undecided answer is recorded, not repeated",
    "--force": "nothing here can be forced; a refusal is a result",
    "--profile": "the profile is the subcell principal's compiled constant, never an argument",
    "--aws-profile": "the profile is the subcell principal's compiled constant, never an argument",
    "--simulate": "simulation never decides a cell; it is not run here",
    "--skip-identity": "the identity proof is not optional",
    "--no-cleanup": "the cleanup is a separately authorized mode, never skipped by flag",
    "--bucket": "buckets come from the bindings, never from an argument",
    "--key": "keys are resolved from the catalogue, never from an argument",
    "--reuse-authorization": "an authorization is consumed by its one execution; never reused",
    "--stamp": "the session stamp is the prepared statement's, never an argument",
    "--task": "the probe task is the one the authorized launch started, never an argument",
    "--exit-code": "an exit code never completes a permission record; the receipt does",
}

EXIT_PLANNED: Final = 0
EXIT_EXECUTED: Final = 0
EXIT_CHECKED: Final = 0
EXIT_REFUSED_ARGUMENTS: Final = 2
EXIT_REFUSED_EXECUTION_CONTEXT: Final = 3
EXIT_REFUSED_IDENTITY: Final = 4
EXIT_REFUSED_BINDING: Final = 5
EXIT_REFUSED_DECLARATION: Final = 6
EXIT_REFUSED_DEPENDENCY: Final = 7
EXIT_REFUSED_RECORD_WRITE: Final = 8
EXIT_INVERTED: Final = 9
EXIT_UNDECIDED: Final = 10
EXIT_CHECK_REFUSED: Final = 11
EXIT_CLEANUP_UNRESOLVED: Final = 12
EXIT_REFUSED_SUBCELL: Final = 13
EXIT_PREPARED: Final = 0
EXIT_REFUSED_PREPARATION: Final = 14
EXIT_REFUSED_AUTHORIZATION: Final = 15
EXIT_REFUSED_AUTHORIZATION_CONSUMED: Final = 16
EXIT_REFUSED_PREREQUISITE: Final = 17
EXIT_PROBE_LAUNCHED: Final = 0
EXIT_PROBE_NOT_STARTED: Final = 18
EXIT_COMPLETED: Final = 0
EXIT_REFUSED_COMPLETION: Final = 19
EXIT_REFUSED_LEDGER: Final = 20
EXIT_REFUSED_RECOVERY_PENDING: Final = 21
EXIT_REFUSED_RESERVATION: Final = 22
EXIT_RECOVERED: Final = 0
EXIT_REFUSED_RECOVERY: Final = 23
EXIT_COMPLETION_RECORDED: Final = 24
EXIT_COLLECTION_NOT_COLLECTED: Final = 25
EXIT_REFUSED_DESTINATION: Final = 26
EXIT_REFUSED_REHEARSAL_CLOSED: Final = 27
EXIT_REFUSED_COLLECTION_RECORDS: Final = 28
EXIT_REFUSED_CONTRADICTION_UNRESOLVED: Final = 29
EXIT_REFUSED_RECEIPT_BINDING: Final = 30
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")
#: The hand-read completion's acknowledgement of one recorded contradiction, by the
#: collection record's digest; repeatable; never accepted with a collection.
ACKNOWLEDGE_FLAG: Final = "--acknowledge-collection-contradiction"

SENTENCES: Final[dict[str, str]] = {
    "planned": "permission subcell plan printed; nothing was performed",
    "executed": "permission subcell executed; the record was written",
    "inverted": "permission subcell INVERTED: the observed answer contradicts the expectation",
    "undecided": "permission subcell UNDECIDED: the answer decided nothing; not re-executed here",
    "checked": "permission record read back",
    "cleaned": "permission cleanup completed; every recorded key confirmed absent",
    "cleanup_unresolved": "permission cleanup UNRESOLVED: residue recorded",
    "refused_arguments": "permission cells refused: the arguments were not admitted",
    "refused_execution_context": "permission cells refused: not run from an owner console",
    "refused_identity": "permission cells refused: the principal's identity did not prove",
    "refused_binding": (
        "permission cells refused: a binding, registration or targets file was not admitted"
    ),
    "refused_declaration": (
        "permission cells refused: the tracked declarations could not be digested"
    ),
    "refused_dependency": "permission cells refused: a client could not be built",
    "refused_record_write": "permission cells refused: the record could not be written",
    "refused_subcell": "permission cells refused: not an executable subcell",
    "check_refused": "permission record check refused",
    "prepared": "permission subcell statement written; nothing was performed",
    "refused_preparation": (
        "permission cells refused: no prepared statement for this subcell under the current "
        "binding, or the statement no longer recomputes (--prepare-subcell again)"
    ),
    "refused_authorization": (
        "permission cells refused: the authorization is not for this statement, or not valid now"
    ),
    "refused_authorization_consumed": (
        "permission cells refused: this authorization was already consumed; one execution per "
        "authorization, whatever followed it"
    ),
    "refused_prerequisite": (
        "permission cells refused: a prerequisite object is not established by a bound record, "
        "or is no longer present"
    ),
    "probe_launched": (
        "permission probe launched and observed; complete the subcell from its hand-read "
        "receipt (--complete-subcell --receipt-lines)"
    ),
    "probe_not_started": (
        "permission probe launch refused before a task started; the authorization is consumed "
        "and the attempt stays interrupted (prepare and authorize again)"
    ),
    "completed": "permission subcell completed from its verified receipt; the record was written",
    "refused_completion": (
        "permission cells refused: no launched, unanswered attempt of this subcell under the "
        "current binding, or the receipt does not verify against its launch record"
    ),
    "refused_ledger": "permission cells refused: the owner ledger could not be updated",
    "refused_recovery_pending": (
        "permission cells refused: a reserved probe launch awaits recovery "
        "(--recover-probe-launch) before any probe is launched"
    ),
    "refused_reservation": (
        "permission cells refused: the probe identity of this statement is already reserved; "
        "the authorization is consumed and the attempt stays interrupted"
    ),
    "recovered": (
        "interrupted probe launch recorded in the owner ledger; nothing was launched, and the "
        "cleanup discovers any started task by the reservation's tag"
    ),
    "refused_recovery": (
        "permission cells refused: no reserved, unrecorded probe launch of this subcell under "
        "the current binding, or its launch record names another specification"
    ),
    "completion_recorded": (
        "permission subcell already completed from this receipt; the record, the receipt "
        "evidence and the ledger row are present and nothing was changed"
    ),
    "collection_not_collected": (
        "receipt not collected: the collection is recorded (outcome and counts, never log "
        "content), the subcell stays as it was, nothing is established about whether a "
        "receipt exists, and the next collection reads the stream again"
    ),
    "refused_collection_records": (
        "permission cells refused: the recorded collections of this launch are malformed, "
        "bound to another launch or stream, carry an unverifiable line, or contradict "
        "each other; nothing is chosen between them"
    ),
    "refused_contradiction_unresolved": (
        "permission cells refused: a recorded collection of this launch found contradictory "
        "receipts and no disposition names it; no collection resolves that -- the owner "
        "reads the stream, completes from a hand-read receipt and acknowledges the record "
        "by digest"
    ),
    "refused_receipt_binding": (
        "permission cells refused: a disposition bound this launch to one hand-read receipt; "
        "only a hand-read completion with that receipt continues, no other receipt does, "
        "and a collection does not"
    ),
    "refused_destination": (
        "permission cells refused: the registration names no log destination for the probe "
        "entry, or not this entry's"
    ),
    "refused_rehearsal_closed": (
        "permission cells refused: the deletion rehearsal path is implemented offline and "
        "CLOSED pending the governance decision (ADR-0049 D-1); the R-8 subcells stay BLOCKED"
    ),
}


class PermissionToolRefusalError(Exception):
    """A closed refusal: a sentence key and an exit code."""

    def __init__(self, key: str, exit_code: int) -> None:
        super().__init__(key)
        self.key = key
        self.exit_code = exit_code


def running_under_automation(env: Mapping[str, str], modules: Mapping[str, object]) -> bool:
    """The same refusal the R-3 tool applies: no CI, no pytest, no import."""
    from production_r3_verification import running_under_automation as under

    return under(env, modules)


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


def plan_lines(cell_id: str | None = None, subcell_id: str | None = None) -> list[str]:
    """The catalogue, one sanitized line per subcell. No value."""
    cells = pc.SUBCELLS
    if subcell_id is not None:
        cells = (pc.subcell(subcell_id),)
    elif cell_id is not None:
        cells = pc.subcells_of(cell_id)
        if not cells:
            raise ValueError("unknown permission cell")
    lines = []
    for cell in cells:
        lines.append(
            f"subcell={cell.subcell_id} cell={cell.cell_id} principal={cell.principal.value} "
            f"operation={cell.operation.value} target={cell.target.value} "
            f"expect={cell.expectation.value} layer={cell.layer.value}"
            + (f" requires={','.join(cell.requires)}" if cell.requires else "")
            + (" creates=true" if cell.creates else "")
        )
        if cell.blocked_on is not None:
            lines.append(f"  blocked_on: {cell.blocked_on}")
        lines.append(f"  trace: {cell.trace}")
    return lines


# ---------------------------------------------------------------------------
# The declarations, the bindings, the registration
# ---------------------------------------------------------------------------


def declaration_paths(directory: Path = DECLARATION_DIR) -> list[Path]:
    """The tracked declarations every permission record binds to, or ``OSError``.

    The production declarations and the bucket-policy file must all be present: a
    binding over a partial set would bind to nothing the cells test.
    """
    paths = [*sorted(directory.glob("production_*.tf")), directory / "storage.tf"]
    if len(paths) < 2 or not all(p.is_file() for p in paths):
        raise OSError("the tracked declarations are not all present")
    return paths


def current_binding(
    environment: QualificationEnvironmentBinding,
    *,
    registration_bytes: bytes,
    targets: pc.PermissionTargets,
    directory: Path = DECLARATION_DIR,
) -> pc.PermissionBinding:
    """The binding a record made now would carry: every input present, or ``OSError``."""
    return pc.PermissionBinding(
        environment_binding_sha256=environment.digest,
        policy_declaration_sha256=pc.declaration_digest(declaration_paths(directory)),
        registration_sha256=sha256_hex(registration_bytes),
        targets_sha256=targets.digest,
        partition=environment.partition,
        region=environment.region,
    )


def permission_context(
    environment: QualificationEnvironmentBinding,
    *,
    registration_bytes: bytes,
    inputs: Any,
    targets: pc.PermissionTargets,
    production_secret: str | None,
    directory: Path = DECLARATION_DIR,
) -> pc.PermissionContext:
    """What the tool and the cell runner hold every permission result to: the same object."""
    return pc.PermissionContext(
        binding=current_binding(
            environment, registration_bytes=registration_bytes, targets=targets, directory=directory
        ),
        licensed_bucket=environment.licensed_bucket_name,
        inputs=inputs,
        targets=targets,
        production_secret=production_secret,
    )


class _Admitted:
    """Everything the authorized branch admitted before any client existed."""

    __slots__ = ("context", "environment", "store")

    def __init__(
        self,
        *,
        environment: QualificationEnvironmentBinding,
        context: pc.PermissionContext,
        store: Any,
    ) -> None:
        self.environment = environment
        self.context = context
        self.store = store

    @property
    def binding(self) -> pc.PermissionBinding:
        return self.context.binding

    @property
    def targets(self) -> pc.PermissionTargets:
        return self.context.targets

    @property
    def targets_sha256(self) -> str:
        return self.context.binding.targets_sha256

    def resolve(
        self, cell: pc.Subcell, *, stamp: str, prerequisites: Mapping[str, pc.PermissionRecord]
    ) -> pc.ResolvedTarget:
        """The exact target of ``cell`` for ``stamp`` from what was admitted, or refuse."""
        try:
            return self.context.resolve(cell, stamp=stamp, prerequisites=prerequisites)
        except (ValueError, KeyError):
            raise PermissionToolRefusalError("refused_binding", EXIT_REFUSED_BINDING) from None


def _admit(
    parsed: argparse.Namespace,
    env: Mapping[str, str],
    *,
    expected_account: Callable[[], str | None],
    load_environment_binding: Callable[..., Any],
    read_private: Callable[[str], bytes],
    declaration_dir: Path,
    root_source: Callable[[], Path] | None,
) -> _Admitted:
    """The bindings, the registration and the targets, each through its own parser."""
    import production_launch as launch

    from kalpamani.data.production.sharadar.compiled import parse_compiled_configuration
    from kalpamani.data.production.sharadar.launch_records import (
        MAX_RECORD_BYTES,
        LaunchRecordError,
        parse_launch_inputs,
    )

    source = env.get(ENVIRONMENT_BINDING_ENV_VAR, "")
    try:
        account = expected_account()
        environment = load_environment_binding(path=source, expected_account=account)
    except Exception:
        raise PermissionToolRefusalError("refused_binding", EXIT_REFUSED_BINDING) from None
    if (
        type(environment) is not QualificationEnvironmentBinding
        or type(account) is not str
        or environment.target_account_id != account
        or environment.partition != EXPECTED_PARTITION
        or environment.region != EXPECTED_REGION
    ):
        raise PermissionToolRefusalError("refused_binding", EXIT_REFUSED_BINDING)
    try:
        registration_bytes = Path(parsed.launch_inputs).read_bytes()
        if len(registration_bytes) > MAX_RECORD_BYTES:
            raise ValueError("oversize")
        inputs = parse_launch_inputs(registration_bytes)
    except (OSError, ValueError, LaunchRecordError):
        raise PermissionToolRefusalError("refused_binding", EXIT_REFUSED_BINDING) from None
    targets_source = env.get(TARGETS_ENV_VAR, "")
    try:
        targets = pc.parse_permission_targets(read_private(targets_source))
    except Exception:
        raise PermissionToolRefusalError("refused_binding", EXIT_REFUSED_BINDING) from None
    production_secret: str | None = None
    if parsed.acquisition_configuration is not None:
        try:
            configuration, _digest = parse_compiled_configuration(
                Path(parsed.acquisition_configuration).read_bytes()
            )
            production_secret = configuration.secret_identifier
        except Exception:
            raise PermissionToolRefusalError("refused_binding", EXIT_REFUSED_BINDING) from None
    try:
        context = permission_context(
            environment,
            registration_bytes=registration_bytes,
            inputs=inputs,
            targets=targets,
            production_secret=production_secret,
            directory=declaration_dir,
        )
    except OSError:
        raise PermissionToolRefusalError("refused_declaration", EXIT_REFUSED_DECLARATION) from None
    probe = launch.LaunchArguments(
        actor="acquisition",
        kind="verification",
        identity="verify-permission",
        ledger=Path(parsed.ledger),
        launch_inputs=Path(parsed.launch_inputs),
        records_dir=Path(parsed.records_dir),
        authorization=None,
        slice_path=None,
        run_identities=(),
        production_configuration=None,
        verification_configuration=None,
        acquisition_configuration=None,
        authorized=False,
        complete_row=False,
        recover=False,
        isolation_verdict=False,
        launch_record=None,
        receipt_lines=None,
        reachability_evidence=None,
    )
    try:
        store = launch._store(probe, launch._private_root(root_source))
    except launch.LaunchRefusalError:
        raise PermissionToolRefusalError("refused_binding", EXIT_REFUSED_BINDING) from None
    return _Admitted(environment=environment, context=context, store=store)


# ---------------------------------------------------------------------------
# Identity, per principal
# ---------------------------------------------------------------------------


def prove_identity(
    principal: pc.Principal,
    *,
    env: Mapping[str, str],
    caller_identity: Callable[[], object],
    foundation_gate: Callable[[], str | None],
    qualification_gate: Callable[[str], str | None],
    root_source: Callable[[], Path] | None,
    security_of: Callable[[Path], Any] | None,
) -> None:
    """Refuse unless the ambient profile is the principal's and its identity proves.

    A production human or launcher proves through the accepted human bootstrap against
    its own private binding (the same proof the launch tool makes); a qualification actor
    through the accepted ADR-0021 gate; the control principal through the foundation
    gate. A task role or the deletion role has no human proof and is never executed here.
    """
    profile = pc.PRINCIPAL_PROFILE[principal]
    if profile is None or env.get("AWS_PROFILE", "") != profile:
        raise PermissionToolRefusalError("refused_identity", EXIT_REFUSED_IDENTITY)
    actor = pc.PRINCIPAL_ACTOR[principal]
    try:
        if actor is not None:
            from kalpamani.data.production.sharadar.runner import (
                HumanBootstrapOutcome,
                human_bootstrap,
            )

            path = (
                IdentityPath.LAUNCHER
                if principal in (pc.Principal.ACQUISITION_LAUNCHER, pc.Principal.BUILD_LAUNCHER)
                else IdentityPath.HUMAN
            )
            report = human_bootstrap(
                actor=actor,
                path=path,
                environment=env.get,
                caller_identity=caller_identity,
                root_source=root_source,
                security_of=security_of,
            )
            if report.outcome is not HumanBootstrapOutcome.IDENTITY_PROVEN:
                raise PermissionToolRefusalError("refused_identity", EXIT_REFUSED_IDENTITY)
            return
        if principal is pc.Principal.CONTROL:
            reason = foundation_gate()
        else:
            reason = qualification_gate(
                "acquisition"
                if principal is pc.Principal.QUALIFICATION_ACQUISITION
                else "assessment"
            )
    except PermissionToolRefusalError:
        raise
    except Exception:
        raise PermissionToolRefusalError("refused_identity", EXIT_REFUSED_IDENTITY) from None
    if reason is not None:
        raise PermissionToolRefusalError("refused_identity", EXIT_REFUSED_IDENTITY)


# ---------------------------------------------------------------------------
# The authorized branches
# ---------------------------------------------------------------------------


def _evidence(admitted: _Admitted) -> Any:
    """Every permission record, attempt, statement, consumption and cleanup, in context."""
    from production_verification_cells import permission_evidence

    return permission_evidence(admitted.store, admitted.context)


def _bound_prerequisites(
    cell: pc.Subcell, evidence: Any, binding: pc.PermissionBinding
) -> dict[str, pc.PermissionRecord]:
    """The exact bound MATCHED record of each prerequisite whose object is present, or refuse.

    The record must bind through its whole chain (the one validator, ``pc.bind_result``:
    attempt, statement, exact target, consumed authorization), must have created its
    object, and must not have been settled by a later cleanup naming that attempt and
    object: a dependent read against an object the cleanup already settled would read
    nothing.
    """
    bound: dict[str, pc.PermissionRecord] = {}
    for required in cell.requires:
        candidates: list[pc.PermissionRecord] = []
        for r in evidence.records.get(required, ()):
            if r.binding != binding or r.outcome is not pc.SubcellOutcome.MATCHED:
                continue
            if r.created_key is None or r.created_bucket is None:
                continue
            try:
                chain = pc.bind_result(r, evidence)
            except pc.ChainError:
                continue
            if pc.unsettled_reason(chain, evidence.cleanups) is None:
                continue  # already settled: the object is gone
            candidates.append(r)
        if not candidates:
            raise PermissionToolRefusalError("refused_prerequisite", EXIT_REFUSED_PREREQUISITE)
        bound[required] = sorted(candidates, key=lambda r: r.started_at)[-1]
    return bound


def prepare_subcell(
    subcell_id: str,
    parsed: argparse.Namespace,
    *,
    env: Mapping[str, str],
    seams: dict[str, Any],
) -> pc.PermissionStatement:
    """Write the statement of one execution: the exact target, bound prerequisites, binding.

    No identity proof and no client: preparation reads the bindings and the records and
    writes one record. The statement's digest is what the owner's authorization names.
    """
    try:
        cell = pc.subcell(subcell_id)
    except ValueError:
        raise PermissionToolRefusalError("refused_subcell", EXIT_REFUSED_SUBCELL) from None
    if cell.layer not in pc.EXECUTABLE_LAYERS:
        raise PermissionToolRefusalError("refused_subcell", EXIT_REFUSED_SUBCELL)
    now: Callable[[], datetime] = seams["now"]
    admitted = _admit(
        parsed,
        env,
        expected_account=seams["expected_account"],
        load_environment_binding=seams["load_environment_binding"],
        read_private=seams["read_private"],
        declaration_dir=seams.get("declaration_dir", DECLARATION_DIR),
        root_source=seams.get("root_source"),
    )
    if cell.layer in pc.PROBE_LAYERS:
        _probe_target(admitted, cell)
    evidence = _evidence(admitted)
    prerequisites = _bound_prerequisites(cell, evidence, admitted.binding)
    stamp = r3.new_stamp(now())
    target = admitted.resolve(cell, stamp=stamp, prerequisites=prerequisites)
    statement = pc.statement_for(
        cell,
        target=target,
        stamp=stamp,
        binding=admitted.binding,
        targets_sha256=admitted.targets_sha256,
        prerequisites=prerequisites,
        prepared_at=now(),
    )
    try:
        admitted.store.write_record(
            "permission-statement", statement.document(), at=statement.prepared_at
        )
    except Exception:
        raise PermissionToolRefusalError(
            "refused_record_write", EXIT_REFUSED_RECORD_WRITE
        ) from None
    return statement


def _prepared_statement(
    cell: pc.Subcell, admitted: _Admitted, evidence: Any, statement_sha256: str
) -> tuple[pc.PermissionStatement, pc.ResolvedTarget, dict[str, pc.PermissionRecord]]:
    """The prepared statement of ``cell`` the authorization names, recomputed.

    The statement is recomputed from its own stamp against what is admitted NOW -- the
    bindings, the targets document, the prerequisite records -- and must equal the
    prepared one byte for byte: a changed target, targets file, declaration,
    registration or prerequisite is not what the owner authorized.
    """
    prepared = [
        s
        for s in evidence.statements.get(cell.subcell_id, ())
        if s.binding == admitted.binding and s.digest == statement_sha256
    ]
    if len(prepared) != 1:
        raise PermissionToolRefusalError("refused_preparation", EXIT_REFUSED_PREPARATION)
    statement = prepared[0]
    prerequisites = _bound_prerequisites(cell, evidence, admitted.binding)
    target = admitted.resolve(cell, stamp=statement.stamp, prerequisites=prerequisites)
    recomputed = pc.statement_for(
        cell,
        target=target,
        stamp=statement.stamp,
        binding=admitted.binding,
        targets_sha256=admitted.targets_sha256,
        prerequisites=prerequisites,
        prepared_at=statement.prepared_at,
    )
    if recomputed.digest != statement.digest:
        raise PermissionToolRefusalError("refused_preparation", EXIT_REFUSED_PREPARATION)
    return statement, target, prerequisites


def execute_subcell(
    subcell_id: str,
    parsed: argparse.Namespace,
    *,
    env: Mapping[str, str],
    modules: Mapping[str, object],
    seams: dict[str, Any],
) -> pc.PermissionRecord | ProbeLaunchResult:
    """The authorized branch: one subcell, on injected seams.

    A runtime subcell returns its record; a probe-layer subcell (ADR-0048)
    returns the launch it made and, for a held subcell, the record written at once.
    """
    if running_under_automation(env, modules):
        raise PermissionToolRefusalError(
            "refused_execution_context", EXIT_REFUSED_EXECUTION_CONTEXT
        )
    try:
        cell = pc.subcell(subcell_id)
    except ValueError:
        raise PermissionToolRefusalError("refused_subcell", EXIT_REFUSED_SUBCELL) from None
    if cell.layer not in pc.EXECUTABLE_LAYERS:
        raise PermissionToolRefusalError("refused_subcell", EXIT_REFUSED_SUBCELL)
    if cell.layer in pc.PROBE_LAYERS:
        return _execute_probe(cell, parsed, env=env, seams=seams)
    now: Callable[[], datetime] = seams["now"]
    client_factory: Callable[[str, str], pc.PermissionClient] = seams["client_factory"]
    profile = pc.PRINCIPAL_PROFILE[cell.principal]
    assert profile is not None
    # Identity first: a client for the operation exists only after the proof.
    prove_identity(
        cell.principal,
        env=env,
        caller_identity=lambda: seams["caller_identity"](profile),
        foundation_gate=seams["foundation_gate"],
        qualification_gate=seams["qualification_gate"],
        root_source=seams.get("root_source"),
        security_of=seams.get("security_of"),
    )
    admitted = _admit(
        parsed,
        env,
        expected_account=seams["expected_account"],
        load_environment_binding=seams["load_environment_binding"],
        read_private=seams["read_private"],
        declaration_dir=seams.get("declaration_dir", DECLARATION_DIR),
        root_source=seams.get("root_source"),
    )
    evidence = _evidence(admitted)
    # The authorization: for this subcell, valid now, naming one prepared statement that
    # still recomputes; then consumed durably beside the ledger BEFORE anything is attempted.
    from kalpamani.data.production.sharadar.launch_records import MAX_RECORD_BYTES
    from kalpamani.data.production.sharadar.launch_store import StoreDefect, StoreError

    try:
        raw = Path(parsed.authorization).read_bytes()
        if len(raw) > MAX_RECORD_BYTES:
            raise ValueError("oversize")
        authorization = pc.parse_permission_authorization(
            raw, subcell_id=cell.subcell_id, statement_sha256=None, now=now()
        )
    except Exception:
        raise PermissionToolRefusalError(
            "refused_authorization", EXIT_REFUSED_AUTHORIZATION
        ) from None
    statement, target, _prerequisites = _prepared_statement(
        cell, admitted, evidence, authorization.statement_sha256
    )
    started_at = now()
    consumption = pc.PermissionConsumption(
        subcell_id=cell.subcell_id,
        statement_sha256=statement.digest,
        authorization_sha256=authorization.digest,
        consumed_at=started_at,
    )
    try:
        admitted.store.consume(CONSUMPTION_KIND, authorization.digest, consumption.document())
    except StoreError as error:
        if error.defect is StoreDefect.AUTHORIZATION_CONSUMED:
            raise PermissionToolRefusalError(
                "refused_authorization_consumed", EXIT_REFUSED_AUTHORIZATION_CONSUMED
            ) from None
        raise PermissionToolRefusalError(
            "refused_record_write", EXIT_REFUSED_RECORD_WRITE
        ) from None
    attempt = pc.PermissionAttempt(
        subcell_id=cell.subcell_id,
        principal=cell.principal,
        stamp=statement.stamp,
        authorization_sha256=authorization.digest,
        statement_sha256=statement.digest,
        bucket=target.bucket if cell.creates else None,
        key=target.key if cell.creates else None,
        started_at=started_at,
        binding=admitted.binding,
    )
    try:
        admitted.store.write_record("permission-attempt", attempt.document(), at=started_at)
    except Exception:
        raise PermissionToolRefusalError(
            "refused_record_write", EXIT_REFUSED_RECORD_WRITE
        ) from None
    try:
        client = client_factory(profile, admitted.environment.region)
    except Exception:
        raise PermissionToolRefusalError("refused_dependency", EXIT_REFUSED_DEPENDENCY) from None
    record = pc.run_subcell(
        cell,
        target=target,
        attempt=attempt,
        prerequisites=statement.prerequisites,
        client=client,
        identity_verified=True,
        now=now(),
    )
    try:
        admitted.store.write_record("permission-record", record.document(), at=record.finished_at)
    except Exception:
        raise PermissionToolRefusalError(
            "refused_record_write", EXIT_REFUSED_RECORD_WRITE
        ) from None
    return record


def _probe_target(admitted: _Admitted, cell: pc.Subcell) -> Any:
    """The registered permission-probe target of the subcell's actor, or refuse."""
    from kalpamani.data.production.sharadar.launch_records import LaunchKind

    actor = pc.PRINCIPAL_ACTOR[cell.principal]
    target = (
        None
        if actor is None
        else admitted.context.inputs.targets.get((actor, LaunchKind.PERMISSION_PROBE))
    )
    if target is None:
        raise PermissionToolRefusalError("refused_binding", EXIT_REFUSED_BINDING)
    return target


class ProbeLaunchResult:
    """What executing a probe-layer subcell produced: a launch (and, held, a record)."""

    __slots__ = ("attempt", "record", "report", "task_started")

    def __init__(
        self, *, attempt: pc.PermissionAttempt, report: Any, record: pc.PermissionRecord | None
    ) -> None:
        self.attempt = attempt
        self.report = report
        self.record = record
        self.task_started = bool(report.task_started)


def _consume_and_attempt(
    cell: pc.Subcell,
    parsed: argparse.Namespace,
    admitted: _Admitted,
    evidence: Any,
    *,
    now: datetime,
) -> tuple[pc.PermissionAttempt, pc.PermissionStatement, pc.ResolvedTarget, Any]:
    """The authorization admitted for the prepared statement, consumed; the attempt written."""
    from kalpamani.data.production.sharadar.launch_records import MAX_RECORD_BYTES
    from kalpamani.data.production.sharadar.launch_store import StoreDefect, StoreError

    try:
        raw = Path(parsed.authorization).read_bytes()
        if len(raw) > MAX_RECORD_BYTES:
            raise ValueError("oversize")
        authorization = pc.parse_permission_authorization(
            raw, subcell_id=cell.subcell_id, statement_sha256=None, now=now
        )
    except Exception:
        raise PermissionToolRefusalError(
            "refused_authorization", EXIT_REFUSED_AUTHORIZATION
        ) from None
    statement, target, _prerequisites = _prepared_statement(
        cell, admitted, evidence, authorization.statement_sha256
    )
    consumption = pc.PermissionConsumption(
        subcell_id=cell.subcell_id,
        statement_sha256=statement.digest,
        authorization_sha256=authorization.digest,
        consumed_at=now,
    )
    try:
        admitted.store.consume(CONSUMPTION_KIND, authorization.digest, consumption.document())
    except StoreError as error:
        if error.defect is StoreDefect.AUTHORIZATION_CONSUMED:
            raise PermissionToolRefusalError(
                "refused_authorization_consumed", EXIT_REFUSED_AUTHORIZATION_CONSUMED
            ) from None
        raise PermissionToolRefusalError(
            "refused_record_write", EXIT_REFUSED_RECORD_WRITE
        ) from None
    attempt = pc.PermissionAttempt(
        subcell_id=cell.subcell_id,
        principal=cell.principal,
        stamp=statement.stamp,
        authorization_sha256=authorization.digest,
        statement_sha256=statement.digest,
        bucket=target.bucket if cell.creates else None,
        key=target.key if cell.creates else None,
        started_at=now,
        binding=admitted.binding,
    )
    try:
        admitted.store.write_record("permission-attempt", attempt.document(), at=now)
    except Exception:
        raise PermissionToolRefusalError(
            "refused_record_write", EXIT_REFUSED_RECORD_WRITE
        ) from None
    return attempt, statement, target, authorization


def _execute_probe(
    cell: pc.Subcell, parsed: argparse.Namespace, *, env: Mapping[str, str], seams: dict[str, Any]
) -> ProbeLaunchResult:
    """A probe-layer subcell: consume, attempt, then the accepted launch sequence.

    The actor's human and launcher identities are proven exactly as the launch tool
    proves them (the accepted human bootstrap against the actor's private binding, then
    each path's before-and-after STS proof inside the sequence). The probe input names
    the subcell, the statement, the attempt, the stamp and the exact target; the
    ``RunTask`` is the registered probe revision with the session's ``startedBy`` tag and
    no override. A held subcell makes the launcher's ExecuteCommand check while the task
    runs and writes its record at once; a task subcell's record waits for the receipt.
    """
    from dataclasses import replace

    from kalpamani.data.production.sharadar import launch_records as lr
    from kalpamani.data.production.sharadar.compute import Ec2InterfaceAdapter, EcsTaskAdapter
    from kalpamani.data.production.sharadar.identity import (
        ProvenIdentity,
        production_identity_refusal,
    )
    from kalpamani.data.production.sharadar.inputs import input_digest
    from kalpamani.data.production.sharadar.launch_store import (
        Reservation,
        StoreDefect,
        StoreError,
    )
    from kalpamani.data.production.sharadar.launcher import (
        HeldTask,
        LaunchAdapters,
        LaunchAuthorization,
        launch_authorized_run,
    )
    from kalpamani.data.production.sharadar.outcomes import HeldCheckOutcome, LaunchOutcome
    from kalpamani.data.production.sharadar.parameters import SsmParameterAdapter
    from kalpamani.data.production.sharadar.runner import HumanBootstrapOutcome, human_bootstrap
    from kalpamani.data.production.sharadar.vocabulary import IdentityPath, constants_for

    now: Callable[[], datetime] = seams["now"]
    actor = pc.PRINCIPAL_ACTOR[cell.principal]
    assert actor is not None
    constants = constants_for(actor)
    profile_of = {
        IdentityPath.HUMAN: constants.profile,
        IdentityPath.LAUNCHER: constants.launcher_profile,
    }
    launch_clients = seams["launch_clients"]

    def caller_identity_under(path: IdentityPath) -> Callable[[], object]:
        def call() -> object:
            return launch_clients.sts(profile_of[path]).get_caller_identity()

        return call

    # Identity first, both paths, through the accepted human bootstrap: no parameter and
    # no ECS call exists before both proofs.
    binding: Any = None
    for path in (IdentityPath.HUMAN, IdentityPath.LAUNCHER):
        try:
            bootstrap = human_bootstrap(
                actor=actor,
                path=path,
                environment=env.get,
                caller_identity=caller_identity_under(path),
                root_source=seams.get("root_source"),
                security_of=seams.get("security_of"),
            )
        except Exception:
            raise PermissionToolRefusalError("refused_identity", EXIT_REFUSED_IDENTITY) from None
        if bootstrap.outcome is not HumanBootstrapOutcome.IDENTITY_PROVEN:
            raise PermissionToolRefusalError("refused_identity", EXIT_REFUSED_IDENTITY)
        binding = bootstrap.binding

    def identity_proof(path: IdentityPath) -> str | None:
        verdict = production_identity_refusal(
            actor, path=path, binding=binding, caller_identity=caller_identity_under(path)
        )
        return None if isinstance(verdict, ProvenIdentity) else verdict

    admitted = _admit(
        parsed,
        env,
        expected_account=seams["expected_account"],
        load_environment_binding=seams["load_environment_binding"],
        read_private=seams["read_private"],
        declaration_dir=seams.get("declaration_dir", DECLARATION_DIR),
        root_source=seams.get("root_source"),
    )
    probe_target = _probe_target(admitted, cell)
    evidence = _evidence(admitted)
    # An interrupted probe launch -- reserved beside the ledger, never recorded -- must
    # be recovered before another probe is launched; checked before any authorization is
    # consumed, so a refusal here consumes nothing.
    try:
        ledger, _digest = admitted.store.read_ledger()
        pending_recovery = admitted.store.unreconciled(ledger)
    except (StoreError, lr.LaunchRecordError):
        raise PermissionToolRefusalError("refused_binding", EXIT_REFUSED_BINDING) from None
    if pending_recovery:
        raise PermissionToolRefusalError("refused_recovery_pending", EXIT_REFUSED_RECOVERY_PENDING)
    started_at = now()
    attempt, statement, target, _authorization = _consume_and_attempt(
        cell, parsed, admitted, evidence, now=started_at
    )
    stamp = statement.stamp
    try:
        compiled, _target = lr.compile_launch(
            admitted.context.inputs, actor=actor, kind=lr.LaunchKind.PERMISSION_PROBE
        )
        compiled = replace(compiled, started_by=pc.started_by_of(stamp))
    except Exception:
        raise PermissionToolRefusalError("refused_binding", EXIT_REFUSED_BINDING) from None
    held = cell.layer is pc.Layer.L3_HELD_TASK
    probe_input = pp.PermissionProbeInput(
        actor=actor,
        identity=pp.probe_identity(stamp),
        subcell_id=cell.subcell_id,
        statement_sha256=statement.digest,
        attempt_sha256=attempt.digest,
        stamp=stamp,
        target=target.document(),
        hold_seconds=PROBE_HOLD_SECONDS if held else 0,
        issued_at=started_at,
        expires_at=started_at + pp.MAX_PROBE_INPUT_VALIDITY,
    )
    input_bytes = canonical_bytes(probe_input.document())
    # The durable pre-launch attribution: the probe identity is reserved beside the
    # ledger, exclusively, with the whole specification -- the registered probe target
    # and placement, and the workload naming this subcell, statement, attempt, stamp,
    # tag, hold and input digest -- BEFORE any client exists and before RunTask. An
    # interrupted launch is attributable from this reservation alone; the launch record,
    # when one is written, names this specification's digest and binds to it.
    try:
        with admitted.store.locked(now=now):
            ledger, _digest = admitted.store.read_ledger()
            if admitted.store.unreconciled(ledger):
                raise PermissionToolRefusalError(
                    "refused_recovery_pending", EXIT_REFUSED_RECOVERY_PENDING
                )
            specification = lr.probe_specification(
                ledger=ledger,
                inputs=admitted.context.inputs,
                actor=actor,
                identity=probe_input.identity,
                subcell_id=cell.subcell_id,
                statement_sha256=statement.digest,
                attempt_sha256=attempt.digest,
                stamp=stamp,
                hold_seconds=probe_input.hold_seconds,
                input_digest=input_digest(input_bytes),
            )
            if admitted.store.reservation(probe_input.identity) is not None:
                raise PermissionToolRefusalError("refused_reservation", EXIT_REFUSED_RESERVATION)
            admitted.store.reserve(
                Reservation(
                    identity=probe_input.identity,
                    actor=actor,
                    kind=lr.LaunchKind.PERMISSION_PROBE,
                    specification=specification,
                    reserved_at=started_at,
                )
            )
    except StoreError as error:
        if error.defect is StoreDefect.LEDGER_LOCKED:
            raise PermissionToolRefusalError("refused_ledger", EXIT_REFUSED_LEDGER) from None
        if error.defect is StoreDefect.RESERVATION_EXISTS:
            raise PermissionToolRefusalError(
                "refused_reservation", EXIT_REFUSED_RESERVATION
            ) from None
        raise PermissionToolRefusalError(
            "refused_record_write", EXIT_REFUSED_RECORD_WRITE
        ) from None
    except lr.LaunchRecordError:
        raise PermissionToolRefusalError("refused_binding", EXIT_REFUSED_BINDING) from None
    try:
        authorization = LaunchAuthorization(identity=probe_input.identity, input_bytes=input_bytes)
        adapters = LaunchAdapters(
            ecs=EcsTaskAdapter(
                ecs=launch_clients.ecs(constants.launcher_profile), compiled=compiled
            ),
            ec2=Ec2InterfaceAdapter(ec2=launch_clients.ec2(constants.launcher_profile)),
            human_parameters=SsmParameterAdapter(ssm=launch_clients.ssm(constants.profile)),
            launcher_parameters=SsmParameterAdapter(
                ssm=launch_clients.ssm(constants.launcher_profile)
            ),
        )
    except Exception:
        raise PermissionToolRefusalError("refused_dependency", EXIT_REFUSED_DEPENDENCY) from None

    held_issue: dict[str, Any] = {}

    def while_running(held_task: HeldTask) -> None:
        # The launcher's one ExecuteCommand against its own released probe task, admitted
        # only on the launcher's fresh RUNNING description of exactly that task.
        client_factory: Callable[[str, str], pc.PermissionClient] = seams["client_factory"]
        client = client_factory(constants.launcher_profile, admitted.environment.region)
        aimed = replace(target, task_arn=held_task.task_arn)
        held_issue["issue"] = pc.issue_subcell(cell, target=aimed, client=client, stamp=stamp)
        held_issue["at"] = now()

    report = launch_authorized_run(
        compiled=compiled,
        adapters=adapters,
        authorization=authorization,
        identity_proof=identity_proof,
        now=now,
        monotonic=seams["monotonic"],
        sleep=seams["sleep"],
        while_running=while_running if held else None,
    )
    recorded_at = now()
    record: pc.PermissionRecord | None = None
    held_evidence: pc.HeldTaskEvidence | None = None
    if held:
        issue = held_issue.get("issue")
        if issue is not None:
            record = pc.record_of(
                cell,
                issue=issue,
                attempt=attempt,
                prerequisites=statement.prerequisites,
                identity_verified=True,
                now=recorded_at,
            )
        elif report.handle is not None and report.held_check is not HeldCheckOutcome.NOT_APPLICABLE:
            # A task started, the release was written and the precondition did not hold
            # (stopped first, not running at the ceiling, undescribable, another revision
            # or image) -- or the check raised before an answer was recorded: nothing was
            # issued, the record says so (UNDECIDED, NOT_EXERCISED) and the held-task
            # evidence says why. A launch that never reached the release (a misplacement,
            # a refused release) writes no record: the attempt stays INTERRUPTED.
            record = pc.PermissionRecord(
                subcell_id=cell.subcell_id,
                cell_id=cell.cell_id,
                principal=cell.principal,
                operation=cell.operation,
                target=cell.target,
                expectation=cell.expectation,
                stamp=stamp,
                attempt_sha256=attempt.digest,
                authorization_sha256=attempt.authorization_sha256,
                prerequisites=dict(statement.prerequisites),
                observed=pc.ObservedClass.NOT_EXERCISED,
                outcome=pc.SubcellOutcome.UNDECIDED,
                created_bucket=None,
                created_key=None,
                possibly_created=False,
                started_task_ids=(pc._task_id(report.handle.task_arn),),
                stop_acknowledged_ids=(),
                started_by=pc.started_by_of(stamp),
                possibly_started=False,
                operations=0,
                identity_verified=True,
                started_at=attempt.started_at,
                finished_at=recorded_at,
                binding=admitted.binding,
            )
        # The sequence never started a task: nothing to hold, no record; the attempt
        # stays unanswered (INTERRUPTED) and the cleanup discovers by the tag.
        if report.handle is not None:
            fresh = report.held_task
            held_evidence = pc.HeldTaskEvidence(
                subcell_id=cell.subcell_id,
                attempt_sha256=attempt.digest,
                identity=probe_input.identity,
                task_id=pc._task_id(report.handle.task_arn),
                task_definition_arn=(
                    compiled.task_definition_arn if fresh is None else fresh.task_definition_arn
                ),
                image_digest=None if fresh is None else fresh.image_digest,
                last_status=None if fresh is None else fresh.last_status,
                check=report.held_check,
                describe_calls=0 if fresh is None else fresh.describe_calls,
                observed_at=recorded_at if fresh is None else fresh.observed_at,
                binding=admitted.binding,
            )
            if report.held_check is HeldCheckOutcome.INVOKED and issue is None:
                # The check was admitted and its answer was never recorded (the check
                # itself failed): the evidence keeps the description, the record decides
                # nothing, and the validator never reads it as a verdict.
                held_evidence = replace(held_evidence, check=HeldCheckOutcome.INVOKED)
    # The launch record and the owner-ledger row, under the ledger lock, exactly as the
    # launch tool writes them: every launched identity is in the ledger, probe or not.
    outcome = lr.provisional_ledger_outcome(
        kind=lr.LaunchKind.PERMISSION_PROBE,
        task_started=report.task_started,
        misplaced=report.outcome is LaunchOutcome.MISPLACED,
        exit_codes=report.task_exit_codes,
    )
    from kalpamani.data.production.sharadar.entry import TaskEntry

    entry = (
        TaskEntry.ACQUISITION_PROBE
        if actor is ProductionActor.ACQUISITION
        else TaskEntry.BUILD_PROBE
    )
    launch_record: Any = None
    if report.handle is not None:
        launch_record = lr.LaunchRecord(
            entry=entry,
            kind=lr.LaunchKind.PERMISSION_PROBE,
            identity=probe_input.identity,
            task_arn=report.handle.task_arn,
            task_definition_arn=compiled.task_definition_arn,
            image_digest=compiled.image_digest,
            configuration_digest=compiled.configuration_digest,
            code_commit=probe_target.code_commit,
            input_digest=input_digest(authorization.input_bytes),
            slice=None,
            plan_digest=None,
            launched_at=started_at,
            recorded_at=recorded_at,
            network_interface_id=report.network_interface_id,
            subnet_id=report.subnet_id,
            security_group_ids=report.security_group_ids,
            specification_digest=specification.digest,
            observed_exit_code=report.observed_exit_code,
        )
        row = lr.provisional_ledger_row(launch_record, outcome=outcome, completed_at=recorded_at)
    else:
        row = lr.OwnerLedgerRow(
            identity=probe_input.identity,
            actor=actor,
            kind=lr.LaunchKind.PERMISSION_PROBE,
            outcome=outcome,
            evidence=lr.LedgerEvidence.EXIT_CODE_ONLY,
            launched_at=started_at,
            completed_at=recorded_at,
            slice=None,
            plan_digest=None,
        )
    evidence_document = lr.evidence_document(
        actor=actor,
        kind=lr.LaunchKind.PERMISSION_PROBE,
        outcome=report.outcome.value,
        counts={
            "parameter_reads": report.counts.parameter_reads,
            "parameter_creates": report.counts.parameter_creates,
            "parameter_deletes": report.counts.parameter_deletes,
            "run_task": report.counts.run_task,
            "describe_tasks": report.counts.describe_tasks,
            "describe_network_interfaces": report.counts.describe_network_interfaces,
            "stop_task": report.counts.stop_task,
            "identity_calls": report.counts.identity_calls,
        },
        incident=None if report.incident is None else report.incident.value,
        cleanup_failures=[f"{f.stage.value}:{f.failure}" for f in report.cleanup_failures],
        task_started=report.task_started,
        exit_codes=list(report.task_exit_codes),
        recorded_at=recorded_at,
    )
    try:
        with admitted.store.locked(now=now):
            ledger, digest = admitted.store.read_ledger()
            ledger = lr.append_row(ledger, row)
            admitted.store.write_record("launch-evidence", evidence_document, at=recorded_at)
            if launch_record is not None:
                admitted.store.write_record(
                    "launch-record", launch_record.document(), at=recorded_at
                )
            if held_evidence is not None:
                admitted.store.write_record("held-task", held_evidence.document(), at=recorded_at)
            if record is not None:
                admitted.store.write_record("permission-record", record.document(), at=recorded_at)
            admitted.store.replace_ledger(ledger, expected_digest=digest)
    except (StoreError, lr.LaunchRecordError) as error:
        defect = getattr(error, "defect", None)
        if defect is StoreDefect.LEDGER_LOCKED:
            raise PermissionToolRefusalError("refused_ledger", EXIT_REFUSED_LEDGER) from None
        raise PermissionToolRefusalError(
            "refused_record_write", EXIT_REFUSED_RECORD_WRITE
        ) from None
    return ProbeLaunchResult(attempt=attempt, report=report, record=record)


class _Completion:
    """One probe launch and what its completion has and has not yet written."""

    __slots__ = ("attempt", "launch", "receipts", "record", "row")

    def __init__(
        self,
        *,
        attempt: pc.PermissionAttempt,
        launch: pc.ProbeLaunch,
        record: pc.PermissionRecord | None,
        receipts: tuple[pc.ProbeReceiptEvidence, ...],
    ) -> None:
        self.attempt = attempt
        self.launch = launch
        self.record = record
        self.receipts = receipts
        self.row = launch.row

    @property
    def complete(self) -> bool:
        from kalpamani.data.production.sharadar.launch_records import LedgerEvidence

        return (
            self.record is not None
            and len(self.receipts) == 1
            and self.row is not None
            and self.row.evidence is LedgerEvidence.RECEIPT_VERIFIED
        )


def _completions(cell: pc.Subcell, admitted: _Admitted, evidence: Any) -> list[_Completion]:
    """Every launched attempt of ``cell`` under the current binding, with what it has."""
    records = {r.attempt_sha256: r for r in evidence.records.get(cell.subcell_id, ())}
    found: list[_Completion] = []
    for attempt in evidence.attempts.get(cell.subcell_id, ()):
        launch = evidence.probe_launches.get(attempt.digest)
        if attempt.binding != admitted.binding or launch is None or launch.record is None:
            continue
        found.append(
            _Completion(
                attempt=attempt,
                launch=launch,
                record=records.get(attempt.digest),
                receipts=evidence.probe_receipts.get(attempt.digest, ()),
            )
        )
    return found


def _receipt_text(parsed: argparse.Namespace, receipt_text: str | None) -> str:
    """The receipt lines: the hand-read file, or the collector's line."""
    if receipt_text is not None:
        return receipt_text
    try:
        return Path(parsed.receipt_lines).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        raise PermissionToolRefusalError("refused_completion", EXIT_REFUSED_COMPLETION) from None


def complete_subcell(
    subcell_id: str,
    parsed: argparse.Namespace,
    *,
    env: Mapping[str, str],
    seams: dict[str, Any],
    receipt_text: str | None = None,
) -> tuple[pc.PermissionRecord, bool]:
    """Complete a launched probe subcell from its hand-read receipt. Offline; no client.

    Exactly one attempt of the subcell under the current binding must have a probe launch
    -- reserved beside the ledger and recorded -- whose completion is not yet whole. The
    receipt verifies against that launch record through the accepted validator (entry,
    code commit, configuration digest, the binding digest over task id, revision, image,
    identity and input digest). For a **task** subcell the permission block must name
    this attempt, its statement, its subcell and its stamp, and the record is written
    with ``identity_verified`` exactly when the probe's bootstrap released (a probe that
    refused before its operation completes as UNDECIDED / ``NOT_EXERCISED``, never
    re-executed here). For a **held** subcell the record was written at launch; the
    receipt completes its evidence. In both cases the receipt is kept as evidence bound
    to the launch record by digest, and the owner-ledger row is completed from it.

    **Repeatable.** An interruption between the record and the ledger (or the receipt
    evidence) leaves a partial completion; running the same completion again with the
    same receipt writes exactly what is missing -- the receipt must then equal what the
    existing record established -- and a completion that is already whole changes
    nothing and says so. Nothing is relaunched, and no evidence is ever removed.
    Returns the record and whether anything was written.
    """
    from kalpamani.data.production.sharadar import launch_records as lr
    from kalpamani.data.production.sharadar.launch_store import StoreDefect, StoreError
    from kalpamani.data.production.sharadar.receipts import (
        ReceiptError,
        collect_receipt_line,
        decode_receipt_line,
        verify_receipt,
    )

    try:
        cell = pc.subcell(subcell_id)
    except ValueError:
        raise PermissionToolRefusalError("refused_subcell", EXIT_REFUSED_SUBCELL) from None
    if cell.layer not in pc.PROBE_LAYERS:
        raise PermissionToolRefusalError("refused_subcell", EXIT_REFUSED_SUBCELL)
    now: Callable[[], datetime] = seams["now"]
    admitted = _admit(
        parsed,
        env,
        expected_account=seams["expected_account"],
        load_environment_binding=seams["load_environment_binding"],
        read_private=seams["read_private"],
        declaration_dir=seams.get("declaration_dir", DECLARATION_DIR),
        root_source=seams.get("root_source"),
    )
    evidence = _evidence(admitted)
    candidates = _completions(cell, admitted, evidence)
    pending = [c for c in candidates if not c.complete]
    if not pending and len(candidates) == 1 and candidates[0].receipts:
        # Already whole: the same receipt changes nothing and says so; another refuses.
        try:
            text = _receipt_text(parsed, receipt_text)
            line = collect_receipt_line(text.splitlines())
            document = decode_receipt_line(line)
        except ReceiptError:
            raise PermissionToolRefusalError(
                "refused_completion", EXIT_REFUSED_COMPLETION
            ) from None
        whole = candidates[0].launch
        if receipt_text is None and whole.record is not None:
            # A completed resolution stays bound to its receipt: another line, even one
            # decoding to the same document, is refused as a substitution.
            _dispositions_for(
                parsed,
                records_dir=admitted.store._records_dir,
                identity=whole.identity,
                launch_record_sha256=pc.launch_record_digest(whole.record),
                receipt_text=text,
                now=now,
            )
        if candidates[0].receipts[0].receipt == document:
            raise PermissionToolRefusalError("completion_recorded", EXIT_COMPLETION_RECORDED)
        raise PermissionToolRefusalError("refused_completion", EXIT_REFUSED_COMPLETION)
    if len(pending) != 1:
        raise PermissionToolRefusalError("refused_completion", EXIT_REFUSED_COMPLETION)
    completion = pending[0]
    attempt, launch = completion.attempt, completion.launch
    launch_record = launch.record
    assert launch_record is not None
    if launch.duplicates or launch.binding is not pc.RecordBinding.BOUND:
        raise PermissionToolRefusalError("refused_completion", EXIT_REFUSED_COMPLETION)
    try:
        text = _receipt_text(parsed, receipt_text)
        document = decode_receipt_line(collect_receipt_line(text.splitlines()))
        verified = verify_receipt(document, expectation=launch_record.expectation())
    except ReceiptError:
        raise PermissionToolRefusalError("refused_completion", EXIT_REFUSED_COMPLETION) from None
    # The receipt's outcome must be the exit the launcher observed at the terminal state.
    from kalpamani.data.production.sharadar.entry import EXIT_STATUS

    if (
        launch_record.observed_exit_code is None
        or EXIT_STATUS.get(verified.outcome) != launch_record.observed_exit_code
    ):
        raise PermissionToolRefusalError("refused_completion", EXIT_REFUSED_COMPLETION)
    dispositions: list[dict[str, Any]] = []
    if receipt_text is None:
        # A hand-read completion over a recorded, unresolved contradiction needs the
        # owner's explicit acknowledgement of that record; it is then disposed, bound to
        # this receipt, and the contradiction record stays exactly as written.
        dispositions = _dispositions_for(
            parsed,
            records_dir=admitted.store._records_dir,
            identity=launch.identity,
            launch_record_sha256=pc.launch_record_digest(launch_record),
            receipt_text=text,
            now=now,
        )
    statements = [
        s
        for s in evidence.statements.get(cell.subcell_id, ())
        if s.digest == attempt.statement_sha256
    ]
    if len(statements) != 1:
        raise PermissionToolRefusalError("refused_completion", EXIT_REFUSED_COMPLETION)
    record = completion.record
    if cell.layer is pc.Layer.L3_TASK:
        observation = verified.permission
        if observation is None:
            # The probe refused before its operation: the answer decided nothing, and the
            # subcell is completed as UNDECIDED rather than left for an automatic retry.
            observation = pp.PermissionProbeObservation(
                subcell_id=cell.subcell_id,
                statement_sha256=attempt.statement_sha256,
                attempt_sha256=attempt.digest,
                stamp=attempt.stamp,
                observed=pc.ObservedClass.NOT_EXERCISED,
                outcome=pc.SubcellOutcome.UNDECIDED,
                created=False,
                possibly_created=False,
                operations=0,
                held_seconds=0,
            )
        try:
            established = pc.record_of_probe(
                cell,
                observation=observation,
                attempt=attempt,
                prerequisites=statements[0].prerequisites,
                probe_task_id=launch_record.task_id,
                identity_verified=verified.released,
                now=now(),
            )
        except ValueError:
            raise PermissionToolRefusalError(
                "refused_completion", EXIT_REFUSED_COMPLETION
            ) from None
        if record is None:
            record = established
        elif _same_result(record, established):
            established = record
        else:
            # A record exists and this receipt establishes something else: not a repeat.
            raise PermissionToolRefusalError("refused_completion", EXIT_REFUSED_COMPLETION)
        record = established
    else:
        if record is None:
            # A held subcell's record is written at launch; a launch without one never
            # reached its hold and is not completed from a receipt.
            raise PermissionToolRefusalError("refused_completion", EXIT_REFUSED_COMPLETION)
    write_record = completion.record is None
    write_receipt = not completion.receipts
    if completion.receipts:
        existing = completion.receipts[0]
        if (
            len(completion.receipts) != 1
            or existing.receipt != document
            or existing.launch_record_sha256 != pc.launch_record_digest(launch_record)
        ):
            raise PermissionToolRefusalError("refused_completion", EXIT_REFUSED_COMPLETION)
    receipt_evidence = pc.ProbeReceiptEvidence(
        subcell_id=cell.subcell_id,
        attempt_sha256=attempt.digest,
        identity=launch.identity,
        launch_record_sha256=pc.launch_record_digest(launch_record),
        receipt=document,
        received_at=now(),
        binding=admitted.binding,
    )
    try:
        with admitted.store.locked(now=now):
            ledger, digest = admitted.store.read_ledger()
            existing_row = ledger.row(launch_record.identity)
            complete_row = (
                existing_row is not None
                and existing_row.evidence is lr.LedgerEvidence.EXIT_CODE_ONLY
            )
            if existing_row is None:
                raise PermissionToolRefusalError("refused_completion", EXIT_REFUSED_COMPLETION)
            if not (write_record or write_receipt or complete_row):
                raise PermissionToolRefusalError("completion_recorded", EXIT_COMPLETION_RECORDED)
            for disposition in dispositions:
                admitted.store.write_record("collection-disposition", disposition, at=now())
            if complete_row:
                try:
                    ledger = lr.complete_ledger_row(ledger, record=launch_record, receipt=verified)
                except lr.LaunchRecordError as error:
                    if error.defect is not lr.LaunchRecordDefect.ROW_NOT_BUILDABLE:
                        raise
                    complete_row = False
            if write_record:
                admitted.store.write_record(
                    "permission-record", record.document(), at=record.finished_at
                )
            if write_receipt:
                admitted.store.write_record(
                    "probe-receipt", receipt_evidence.document(), at=receipt_evidence.received_at
                )
            if complete_row:
                admitted.store.replace_ledger(ledger, expected_digest=digest)
    except (StoreError, lr.LaunchRecordError) as error:
        defect = getattr(error, "defect", None)
        if defect is StoreDefect.LEDGER_LOCKED:
            raise PermissionToolRefusalError("refused_ledger", EXIT_REFUSED_LEDGER) from None
        raise PermissionToolRefusalError(
            "refused_record_write", EXIT_REFUSED_RECORD_WRITE
        ) from None
    return record, True


def collect_receipt_for_subcell(
    subcell_id: str,
    parsed: argparse.Namespace,
    *,
    env: Mapping[str, str],
    modules: Mapping[str, object],
    seams: dict[str, Any],
) -> str:
    """The probe launch's receipt line from its own stream (ADR-0049 s.2), or refuse.

    Exactly one launched, incomplete attempt of the subcell under the current binding; the
    registered probe target's log destination held to the probe entry; the actor's
    launcher identity proven through the accepted human bootstrap; then one bounded
    collection under that profile, recorded (``receipt-collection``) whatever its outcome,
    the line kept only once it verified against the launch record. No collection before
    the launcher observed the probe's terminal state. Every collection record about this
    launch is admitted through the collector's one rule (:func:`admit_collection_records`):
    a verified COLLECTED line is reused and the stream is not read again; a rejected,
    exhausted, incomplete or contradictory attempt never blocks, and the stream is read
    again; malformed, misbound, unverifiable or mutually contradictory records refuse, and
    nothing is chosen between them. The line then completes the subcell through
    :func:`complete_subcell` -- the same verifier, the same evidence, the same binding
    rules as a hand-read receipt.
    """
    from kalpamani.data.production.sharadar.launch_store import StoreError
    from kalpamani.data.production.sharadar.receipt_collector import (
        CollectionRecordDefect,
        CollectionRecordError,
        CollectorError,
        SdkLogsClient,
        admit_collection_records,
        collect_receipt,
        destination_for,
    )
    from kalpamani.data.production.sharadar.runner import HumanBootstrapOutcome, human_bootstrap
    from kalpamani.data.production.sharadar.vocabulary import IdentityPath, constants_for

    if running_under_automation(env, modules):
        raise PermissionToolRefusalError(
            "refused_execution_context", EXIT_REFUSED_EXECUTION_CONTEXT
        )
    try:
        cell = pc.subcell(subcell_id)
    except ValueError:
        raise PermissionToolRefusalError("refused_subcell", EXIT_REFUSED_SUBCELL) from None
    if cell.layer not in pc.PROBE_LAYERS:
        raise PermissionToolRefusalError("refused_subcell", EXIT_REFUSED_SUBCELL)
    now: Callable[[], datetime] = seams["now"]
    admitted = _admit(
        parsed,
        env,
        expected_account=seams["expected_account"],
        load_environment_binding=seams["load_environment_binding"],
        read_private=seams["read_private"],
        declaration_dir=seams.get("declaration_dir", DECLARATION_DIR),
        root_source=seams.get("root_source"),
    )
    evidence = _evidence(admitted)
    candidates = _completions(cell, admitted, evidence)
    pending = [c for c in candidates if not c.complete]
    if len(pending) == 1:
        launch = pending[0].launch
    elif not pending and len(candidates) == 1:
        # Already whole: a recorded collection is handed back so the completion can say
        # so; a completion made from a hand-read receipt has nothing to collect.
        launch = candidates[0].launch
    else:
        raise PermissionToolRefusalError("refused_completion", EXIT_REFUSED_COMPLETION)
    launch_record = launch.record
    assert launch_record is not None
    if launch.duplicates or launch.binding is not pc.RecordBinding.BOUND:
        raise PermissionToolRefusalError("refused_completion", EXIT_REFUSED_COMPLETION)
    if launch_record.observed_exit_code is None:
        # No collection before the launcher observed the terminal state.
        raise PermissionToolRefusalError("refused_completion", EXIT_REFUSED_COMPLETION)
    probe_target = _probe_target(admitted, cell)
    if probe_target.task_definition_arn != launch_record.task_definition_arn:
        raise PermissionToolRefusalError("refused_completion", EXIT_REFUSED_COMPLETION)
    try:
        destination = destination_for(
            launch_record.entry, probe_target.task_definition.log_destination
        )
    except CollectorError:
        raise PermissionToolRefusalError("refused_destination", EXIT_REFUSED_DESTINATION) from None
    record_digest = pc.launch_record_digest(launch_record)
    expectation = launch_record.expectation()
    try:
        admission = admit_collection_records(
            _collection_payloads(admitted.store._records_dir),
            identity=launch.identity,
            launch_record_sha256=record_digest,
            destination=destination,
            task_id=launch_record.task_id,
            expectation=expectation,
        )
    except CollectionRecordError as error:
        if error.defect is CollectionRecordDefect.CONTRADICTION_UNRESOLVED:
            raise PermissionToolRefusalError(
                "refused_contradiction_unresolved", EXIT_REFUSED_CONTRADICTION_UNRESOLVED
            ) from None
        if error.defect is CollectionRecordDefect.RECEIPT_SUBSTITUTED:
            raise PermissionToolRefusalError(
                "refused_receipt_binding", EXIT_REFUSED_RECEIPT_BINDING
            ) from None
        raise PermissionToolRefusalError(
            "refused_collection_records", EXIT_REFUSED_COLLECTION_RECORDS
        ) from None
    except OSError:
        raise PermissionToolRefusalError(
            "refused_collection_records", EXIT_REFUSED_COLLECTION_RECORDS
        ) from None
    if admission.reusable_line is not None:
        return admission.reusable_line
    if admission.bound_receipt_sha256 is not None and pending:
        # A resolution begun by a hand-read completion is finished by one: no read.
        raise PermissionToolRefusalError("refused_receipt_binding", EXIT_REFUSED_RECEIPT_BINDING)
    if not pending:
        raise PermissionToolRefusalError("completion_recorded", EXIT_COMPLETION_RECORDED)
    actor = pc.PRINCIPAL_ACTOR[cell.principal]
    assert actor is not None
    constants = constants_for(actor)
    launch_clients = seams["launch_clients"]
    try:
        bootstrap = human_bootstrap(
            actor=actor,
            path=IdentityPath.LAUNCHER,
            environment=env.get,
            caller_identity=lambda: launch_clients.sts(
                constants.launcher_profile
            ).get_caller_identity(),
            root_source=seams.get("root_source"),
            security_of=seams.get("security_of"),
        )
    except Exception:
        raise PermissionToolRefusalError("refused_identity", EXIT_REFUSED_IDENTITY) from None
    if bootstrap.outcome is not HumanBootstrapOutcome.IDENTITY_PROVEN:
        raise PermissionToolRefusalError("refused_identity", EXIT_REFUSED_IDENTITY)
    try:
        client = SdkLogsClient(lambda _service: launch_clients.logs(constants.launcher_profile))
    except Exception:
        raise PermissionToolRefusalError("refused_dependency", EXIT_REFUSED_DEPENDENCY) from None
    collected = collect_receipt(
        destination=destination,
        task_id=launch_record.task_id,
        expectation=expectation,
        client=client,
        now=now,
        monotonic=seams["monotonic"],
        sleep=seams["sleep"],
    )
    try:
        admitted.store.write_record(
            "receipt-collection",
            collected.document(identity=launch.identity, launch_record_sha256=record_digest),
            at=collected.finished_at,
        )
    except StoreError:
        raise PermissionToolRefusalError(
            "refused_record_write", EXIT_REFUSED_RECORD_WRITE
        ) from None
    print(collected.summary())
    if collected.receipt_line is None:
        raise PermissionToolRefusalError("collection_not_collected", EXIT_COLLECTION_NOT_COLLECTED)
    return collected.receipt_line


def _collection_payloads(records_dir: Path) -> list[bytes]:
    """Every collection record and disposition in the directory, as bytes."""
    paths = [
        *records_dir.glob("receipt-collection-*.json"),
        *records_dir.glob("collection-disposition-*.json"),
    ]
    return [path.read_bytes() for path in sorted(paths)]


def _dispositions_for(
    parsed: argparse.Namespace,
    *,
    records_dir: Path,
    identity: str,
    launch_record_sha256: str,
    receipt_text: str,
    now: Callable[[], datetime],
) -> list[dict[str, Any]]:
    """The disposition documents a hand-read completion writes for the recorded
    contradictions it acknowledges, or refuse.

    Every unresolved contradiction record must be acknowledged by its digest, and every
    acknowledged digest must name a recorded contradiction (unresolved or already
    disposed, so the completion is repeatable); a malformed or misbound record refuses.
    """
    from kalpamani.data.contracts.canonical import sha256_hex
    from kalpamani.data.production.sharadar.receipt_collector import (
        CollectionDisposition,
        CollectionRecordDefect,
        CollectionRecordError,
        ContradictionDisposition,
        contradiction_status,
    )
    from kalpamani.data.production.sharadar.receipts import ReceiptError, collect_receipt_line

    try:
        status = contradiction_status(
            _collection_payloads(records_dir),
            identity=identity,
            launch_record_sha256=launch_record_sha256,
        )
    except CollectionRecordError as error:
        if error.defect is CollectionRecordDefect.RECEIPT_SUBSTITUTED:
            raise PermissionToolRefusalError(
                "refused_receipt_binding", EXIT_REFUSED_RECEIPT_BINDING
            ) from None
        raise PermissionToolRefusalError(
            "refused_collection_records", EXIT_REFUSED_COLLECTION_RECORDS
        ) from None
    except OSError:
        raise PermissionToolRefusalError(
            "refused_collection_records", EXIT_REFUSED_COLLECTION_RECORDS
        ) from None
    acknowledged = set(parsed.acknowledged_contradictions or ())
    known = set(status.unresolved) | set(status.disposed)
    if not set(status.unresolved) <= acknowledged or not acknowledged <= known:
        raise PermissionToolRefusalError(
            "refused_contradiction_unresolved", EXIT_REFUSED_CONTRADICTION_UNRESOLVED
        )
    try:
        line = collect_receipt_line(receipt_text.splitlines())
    except ReceiptError:
        raise PermissionToolRefusalError("refused_completion", EXIT_REFUSED_COMPLETION) from None
    if not status.admits_line(line):
        # A disposition bound this launch to another receipt: no substitution.
        raise PermissionToolRefusalError("refused_receipt_binding", EXIT_REFUSED_RECEIPT_BINDING)
    if not status.unresolved:
        return []
    return [
        CollectionDisposition(
            identity=identity,
            launch_record_sha256=launch_record_sha256,
            contradiction_sha256=digest,
            receipt_line_sha256=sha256_hex(line.encode("utf-8")),
            disposition=ContradictionDisposition.HAND_READ_COMPLETION,
            recorded_at=now(),
        ).document()
        for digest in status.unresolved
    ]


def _same_result(existing: pc.PermissionRecord, established: pc.PermissionRecord) -> bool:
    """Whether a receipt re-establishes exactly what the existing record recorded."""
    return existing.document() | {"finished_at": None} == established.document() | {
        "finished_at": None
    }


def recover_probe_launch(
    subcell_id: str,
    parsed: argparse.Namespace,
    *,
    env: Mapping[str, str],
    seams: dict[str, Any],
) -> str:
    """Record an interrupted probe launch: the reserved identity receives its ledger row.

    The reservation beside the ledger proves the probe identity was consumed and names
    the attempt it was launched for; whether a task ran, the tool does not know from the
    reservation alone. A launch record naming this reservation's specification refines
    the row (a task started; the observed exit, when one was observed, decides between
    ``PROBED`` and ``HALTED``); one naming another specification contradicts it and
    refuses; none at all is an honest ``HALTED`` from the reservation. Nothing is
    launched, nothing is removed, the attempt stays unanswered (INTERRUPTED), and the
    cleanup discovers any started task by the reservation's tag. Repeatable: a
    reservation already in the ledger is not recovered twice.
    """
    from kalpamani.data.production.sharadar import launch_records as lr
    from kalpamani.data.production.sharadar.launch_store import StoreDefect, StoreError

    try:
        cell = pc.subcell(subcell_id)
    except ValueError:
        raise PermissionToolRefusalError("refused_subcell", EXIT_REFUSED_SUBCELL) from None
    if cell.layer not in pc.PROBE_LAYERS:
        raise PermissionToolRefusalError("refused_subcell", EXIT_REFUSED_SUBCELL)
    now: Callable[[], datetime] = seams["now"]
    admitted = _admit(
        parsed,
        env,
        expected_account=seams["expected_account"],
        load_environment_binding=seams["load_environment_binding"],
        read_private=seams["read_private"],
        declaration_dir=seams.get("declaration_dir", DECLARATION_DIR),
        root_source=seams.get("root_source"),
    )
    evidence = _evidence(admitted)
    candidates = [
        (attempt, evidence.probe_launches[attempt.digest])
        for attempt in evidence.attempts.get(cell.subcell_id, ())
        if attempt.binding == admitted.binding
        and attempt.digest in evidence.probe_launches
        and evidence.probe_launches[attempt.digest].row is None
    ]
    if len(candidates) != 1:
        raise PermissionToolRefusalError("refused_recovery", EXIT_REFUSED_RECOVERY)
    _attempt, launch = candidates[0]
    if launch.duplicates or (
        launch.record is not None and launch.binding is not pc.RecordBinding.BOUND
    ):
        raise PermissionToolRefusalError("refused_recovery", EXIT_REFUSED_RECOVERY)
    try:
        with admitted.store.locked(now=now):
            ledger, digest = admitted.store.read_ledger()
            if ledger.row(launch.identity) is not None:
                raise PermissionToolRefusalError("refused_recovery", EXIT_REFUSED_RECOVERY)
            recorded_at = now()
            if launch.record is not None:
                code = launch.record.observed_exit_code
                outcome = lr.provisional_ledger_outcome(
                    kind=lr.LaunchKind.PERMISSION_PROBE,
                    task_started=True,
                    misplaced=False,
                    exit_codes=() if code is None else (code,),
                )
                row = lr.provisional_ledger_row(
                    launch.record, outcome=outcome, completed_at=recorded_at
                )
            else:
                row = lr.OwnerLedgerRow(
                    identity=launch.identity,
                    actor=launch.reservation.actor,
                    kind=lr.LaunchKind.PERMISSION_PROBE,
                    outcome="HALTED",
                    evidence=lr.LedgerEvidence.EXIT_CODE_ONLY,
                    launched_at=launch.reservation.reserved_at,
                    completed_at=max(recorded_at, launch.reservation.reserved_at),
                    slice=None,
                    plan_digest=None,
                )
            admitted.store.replace_ledger(lr.append_row(ledger, row), expected_digest=digest)
    except (StoreError, lr.LaunchRecordError) as error:
        defect = getattr(error, "defect", None)
        if defect is StoreDefect.LEDGER_LOCKED:
            raise PermissionToolRefusalError("refused_ledger", EXIT_REFUSED_LEDGER) from None
        raise PermissionToolRefusalError(
            "refused_record_write", EXIT_REFUSED_RECORD_WRITE
        ) from None
    return row.outcome


def settlement_targets(
    evidence: Any, admitted: _Admitted
) -> tuple[tuple[pc.ObjectToSettle, ...], tuple[pc.TasksToSettle, ...], tuple[str, ...]]:
    """What the cleanup settles under this binding, and what it defers, by exact identity.

    Objects: every record's created or possibly created object, and every attempt no
    record names (the interrupted case), each with the attempt it answers -- unless a
    later cleanup already confirmed that attempt's object absent, or an executable
    subcell that reads the object is **prepared and not yet recorded** (the object is
    kept until that dependent check has run). Tasks: every launching attempt whose record
    started or may have started a task, with the tasks it recorded, unless a later
    cleanup already confirmed them stopped.
    """
    binding = admitted.binding
    objects: dict[tuple[str, str, str], pc.ObjectToSettle] = {}
    tasks: dict[str, pc.TasksToSettle] = {}
    deferred: list[str] = []
    prepared_pending: set[str] = set()
    cluster_arn = admitted.context.inputs.cluster_arn
    for subcell_id, statements in evidence.statements.items():
        cell = pc.subcell(subcell_id)
        if cell.layer not in pc.EXECUTABLE_LAYERS or not cell.requires:
            continue
        if any(s.binding == binding for s in statements) and not any(
            r.binding == binding for r in evidence.records.get(subcell_id, ())
        ):
            prepared_pending.update(cell.requires)

    def settled_object(attempt_sha256: str, bucket: str, key: str, after: datetime) -> bool:
        # The one admissibility rule (binding, timing, verified identity): an unverified
        # cleanup suppresses nothing -- the object is settled again by a verified pass.
        return any(
            c.admissible_for(binding, not_before=after)
            and c.settles_object(attempt_sha256, bucket, key)
            for c in evidence.cleanups
        )

    for subcell_id, records in evidence.records.items():
        for record in records:
            if record.binding != binding:
                continue
            # A bound result is settled by the one validator's rule; an unbound record
            # still names an object or a launch to restore, and is settled by what it and
            # its attempt name (restoration never depends on the chain binding).
            chain: pc.BoundChain | None
            try:
                chain = pc.bind_result(record, evidence)
            except pc.ChainError:
                chain = None
            if chain is not None and pc.unsettled_reason(chain, evidence.cleanups) is None:
                continue
            if record.object_open:
                attempt = next(
                    (
                        a
                        for a in evidence.attempts.get(subcell_id, ())
                        if a.digest == record.attempt_sha256
                    ),
                    None,
                )
                bucket = (
                    record.created_bucket
                    if record.created_key is not None
                    else (attempt.bucket if attempt is not None else None)
                )
                key = (
                    record.created_key
                    if record.created_key is not None
                    else (attempt.key if attempt is not None else None)
                )
                if bucket is None or key is None:
                    continue
                if settled_object(record.attempt_sha256, bucket, key, record.finished_at):
                    continue
                if (
                    record.created_key is not None
                    and record.outcome is pc.SubcellOutcome.MATCHED
                    and subcell_id in prepared_pending
                ):
                    deferred.append(key)
                    continue
                objects[(record.attempt_sha256, bucket, key)] = pc.ObjectToSettle(
                    bucket=bucket, key=key, attempt_sha256=record.attempt_sha256
                )
            if record.launch_open and record.started_by is not None:
                if any(
                    c.admissible_for(binding, not_before=record.finished_at)
                    and c.settles_tasks(record.attempt_sha256, record.started_task_ids)
                    for c in evidence.cleanups
                ):
                    continue
                # Every launched task of a record lives on the one registered cluster --
                # a launching subcell's on the registration's, a probe task's on the
                # cluster its reservation named before the launch.
                probe = evidence.probe_launches.get(record.attempt_sha256)
                tasks[record.attempt_sha256] = pc.TasksToSettle(
                    attempt_sha256=record.attempt_sha256,
                    started_by=record.started_by,
                    cluster_arn=cluster_arn if probe is None else probe.cluster_arn,
                    known_task_ids=record.started_task_ids,
                )
    for subcell_id, attempts in evidence.attempts.items():
        answered = {r.attempt_sha256 for r in evidence.records.get(subcell_id, ())}
        for attempt in attempts:
            if attempt.binding != binding or attempt.digest in answered:
                continue
            if attempt.key is not None and attempt.bucket is not None:
                if not settled_object(
                    attempt.digest, attempt.bucket, attempt.key, attempt.started_at
                ):
                    objects[(attempt.digest, attempt.bucket, attempt.key)] = pc.ObjectToSettle(
                        bucket=attempt.bucket, key=attempt.key, attempt_sha256=attempt.digest
                    )
            cell = pc.subcell(subcell_id)
            # An unanswered launching attempt: its tasks are discovered by the session's
            # tag and confirmed STOPPED. An unanswered probe-layer attempt whose launch
            # was **reserved** (AWAITING_RECEIPT, or interrupted anywhere after the
            # reservation -- before RunTask, after it, before its record): its tasks are
            # discovered on the reservation's cluster by the reservation's tag, with the
            # launch record's task, when one was written, confirmed by exact identity. No
            # post-launch record is needed to account for a started probe.
            probe = evidence.probe_launches.get(attempt.digest)
            if cell.operation in pc._LAUNCHING:
                tasks[attempt.digest] = pc.TasksToSettle(
                    attempt_sha256=attempt.digest,
                    started_by=pc.started_by_of(attempt.stamp),
                    cluster_arn=cluster_arn,
                    known_task_ids=(),
                )
            elif cell.layer in pc.PROBE_LAYERS and probe is not None:
                tasks[attempt.digest] = pc.TasksToSettle(
                    attempt_sha256=attempt.digest,
                    started_by=probe.started_by,
                    cluster_arn=probe.cluster_arn,
                    known_task_ids=probe.known_task_ids,
                )
    # Proposed ADR-0050 (correction 1): every unsettled deletion-rehearsal reservation
    # anchored beside the ledger -- discovered on its own cluster by its own tag, keyed by
    # the reservation's digest -- is settled by this same pass. Read from the store's
    # anchors, so a reservation made from any records directory is settled here.
    import production_deletion_rehearsal_tool as rehearsal

    for target in rehearsal.rehearsal_tasks_to_settle(admitted.store, evidence.cleanups):
        tasks[target.attempt_sha256] = target
    return (
        tuple(objects[k] for k in sorted(objects)),
        tuple(tasks[k] for k in sorted(tasks)),
        tuple(sorted(set(deferred))),
    )


def execute_cleanup(
    parsed: argparse.Namespace,
    *,
    env: Mapping[str, str],
    modules: Mapping[str, object],
    seams: dict[str, Any],
) -> pc.PermissionCleanup:
    """The cleanup branch: the control principal settles every open object and launch."""
    if running_under_automation(env, modules):
        raise PermissionToolRefusalError(
            "refused_execution_context", EXIT_REFUSED_EXECUTION_CONTEXT
        )
    now: Callable[[], datetime] = seams["now"]
    client_factory: Callable[[str, str], pc.PermissionClient] = seams["client_factory"]
    prove_identity(
        pc.Principal.CONTROL,
        env=env,
        caller_identity=lambda: seams["caller_identity"](r3.CONTROL_PROFILE),
        foundation_gate=seams["foundation_gate"],
        qualification_gate=seams["qualification_gate"],
        root_source=seams.get("root_source"),
        security_of=seams.get("security_of"),
    )
    admitted = _admit(
        parsed,
        env,
        expected_account=seams["expected_account"],
        load_environment_binding=seams["load_environment_binding"],
        read_private=seams["read_private"],
        declaration_dir=seams.get("declaration_dir", DECLARATION_DIR),
        root_source=seams.get("root_source"),
    )
    objects, tasks, deferred = settlement_targets(_evidence(admitted), admitted)
    try:
        client = client_factory(r3.CONTROL_PROFILE, admitted.environment.region)
    except Exception:
        raise PermissionToolRefusalError("refused_dependency", EXIT_REFUSED_DEPENDENCY) from None
    cleanup = pc.run_cleanup(
        objects,
        tasks,
        client=client,
        stamp=r3.new_stamp(now()),
        deferred=deferred,
        binding=admitted.binding,
        identity_verified=True,
        now=now(),
        budget=pc.CLEANUP_OPERATIONS_PER_KEY * CLEANUP_MAX_KEYS
        + pc.CLEANUP_OPERATIONS_PER_TASK_MAX * CLEANUP_MAX_LAUNCHES,
    )
    try:
        admitted.store.write_record(
            "permission-cleanup", cleanup.document(), at=cleanup.recorded_at
        )
    except Exception:
        raise PermissionToolRefusalError(
            "refused_record_write", EXIT_REFUSED_RECORD_WRITE
        ) from None
    return cleanup


def statement_lines(statement: pc.PermissionStatement) -> list[str]:
    """The sanitized statement: the subcell, the stamp, the digests. No key, no bucket."""
    return [
        f"subcell={statement.subcell_id} principal={statement.principal.value} "
        f"operation={statement.operation.value} target={statement.target.value} "
        f"stamp={statement.stamp} prerequisites={len(statement.prerequisites)}",
        f"statement_sha256={statement.digest}",
    ]


def result_lines(record: pc.PermissionRecord) -> list[str]:
    """The sanitized result: classes and counts. No key, no bucket, no ARN."""
    lines = [
        f"subcell={record.subcell_id} cell={record.cell_id} expect={record.expectation.value} "
        f"observed={record.observed.value} outcome={record.outcome.value} "
        f"operations={record.operations} created={'yes' if record.created_key else 'no'} "
        f"possibly_created={'yes' if record.possibly_created else 'no'}"
    ]
    if record.started_task_ids or record.possibly_started:
        lines.append(
            f"tasks_started={len(record.started_task_ids)} "
            f"stops_acknowledged={len(record.stop_acknowledged_ids)} "
            f"possibly_started={'yes' if record.possibly_started else 'no'} "
            "termination_confirmed=no (the cleanup confirms)"
        )
    lines.append(f"permission_record_digest={record.digest}")
    return lines


def cleanup_lines(cleanup: pc.PermissionCleanup) -> list[str]:
    stopped = sum(len(t.stopped_ids) for t in cleanup.tasks)
    known = sum(len(t.task_ids) for t in cleanup.tasks)
    return [
        f"cleanup keys={len(cleanup.keys)} confirmed={len(cleanup.confirmed_keys)} "
        f"launches={len(cleanup.tasks)} tasks_known={known} tasks_stopped={stopped} "
        f"deferred={len(cleanup.deferred)} residue={len(cleanup.residue)} "
        f"operations={cleanup.operations} "
        f"budget_exhausted={'yes' if cleanup.budget_exhausted else 'no'}"
    ]


# ---------------------------------------------------------------------------
# The real seams
# ---------------------------------------------------------------------------


def _foundation_gate() -> str | None:
    from aws_foundation_verify import identity_gate

    return identity_gate()


def _qualification_gate(actor: str) -> str | None:
    from aws_foundation_verify import QualificationActor, qualification_identity_gate

    return qualification_identity_gate(QualificationActor(actor))


def _expected_account() -> str | None:
    from aws_foundation_verify import expected_account

    return expected_account()


def _load_environment_binding(*, path: str, expected_account: str | None) -> Any:
    from kalpamani.data.qualify.sharadar.runtime_binding import load_environment_binding

    return load_environment_binding(path=path, expected_account=expected_account)


def _read_private(path: str) -> bytes:
    from kalpamani.data.qualify.sharadar.runtime_binding import (
        private_root,
        read_private_document,
        windows_file_security,
    )

    document = read_private_document(
        path, private_root(), windows_file_security, pc.MAX_PERMISSION_TARGETS_BYTES
    )
    return canonical_bytes(document)


def _caller_identity(profile: str) -> object:
    import boto3  # type: ignore[import-untyped]
    from botocore.config import Config  # type: ignore[import-untyped]

    session = boto3.Session(profile_name=profile, region_name=EXPECTED_REGION)
    client = session.client(
        "sts",
        config=Config(
            retries={"total_max_attempts": 1, "mode": "standard"},
            connect_timeout=CONNECT_TIMEOUT_SECONDS,
            read_timeout=READ_TIMEOUT_SECONDS,
        ),
    )
    return client.get_caller_identity()


class _Boto3PermissionClient(SdkPermissionClient):
    """Every permission operation over one profile's boto3 clients. One attempt each.

    ``total_max_attempts`` counts the initial request; every operation is exactly one
    transport attempt with finite connect and read timeouts. Each client is built lazily
    from the one session, so a subcell constructs only the service it uses. The
    operations themselves are the shared :class:`SdkPermissionClient`'s (the probe task
    issues the same requests over its own credentials, ADR-0048).
    """

    __slots__ = ("_config", "_session")

    def __init__(
        self,
        profile: str,
        region: str,
        *,
        session_factory: Callable[[str, str], Any] | None = None,
    ) -> None:
        from botocore.config import Config

        self._session = (
            self._profile_session(profile, region)
            if session_factory is None
            else session_factory(profile, region)
        )
        self._config = Config(
            retries={"total_max_attempts": 1, "mode": "standard"},
            connect_timeout=CONNECT_TIMEOUT_SECONDS,
            read_timeout=READ_TIMEOUT_SECONDS,
        )
        super().__init__(self._profile_client)

    @staticmethod
    def _profile_session(profile: str, region: str) -> Any:
        import boto3

        return boto3.Session(profile_name=profile, region_name=region)

    def _profile_client(self, service: str) -> Any:
        return self._session.client(service, config=self._config)


def _client_factory(profile: str, region: str) -> pc.PermissionClient:
    return _Boto3PermissionClient(profile, region)


def _launch_clients() -> Any:
    """The launch tool's own profile-pinned clients, for a probe launch."""
    import production_launch as launch

    return launch._Boto3Clients()


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="production_permission_cells",
        description="one R-4..R-9 permission subcell per authorized invocation; refuses by default",
    )
    parser.add_argument("--cell")
    parser.add_argument("--subcell")
    parser.add_argument("--prepare-subcell")
    parser.add_argument("--execute-subcell")
    parser.add_argument("--complete-subcell")
    parser.add_argument("--recover-probe-launch")
    parser.add_argument("--collect-receipt")
    parser.add_argument("--rehearse-deletion")
    parser.add_argument("--prepare-rehearsal")
    parser.add_argument("--collect-rehearsal-receipt")
    parser.add_argument("--complete-rehearsal")
    parser.add_argument("--recover-rehearsal-launch")
    parser.add_argument("--rehearsal-inputs", type=Path)
    parser.add_argument(COLLECT_FLAG, dest="collection_authorized", action="store_true")
    parser.add_argument("--receipt-lines", type=Path)
    parser.add_argument(
        ACKNOWLEDGE_FLAG, dest="acknowledged_contradictions", action="append", default=[]
    )
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument("--check-record", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--launch-inputs", type=Path)
    parser.add_argument("--records-dir", type=Path)
    parser.add_argument("--acquisition-configuration", type=Path)
    parser.add_argument(AUTHORIZATION_FLAG, dest="authorized", action="store_true")
    parser.add_argument(CLEANUP_FLAG, dest="cleanup_authorized", action="store_true")
    return parser


def _seams(
    *,
    now: Callable[[], datetime] | None,
    client_factory: Callable[[str, str], pc.PermissionClient] | None,
    caller_identity: Callable[[str], object] | None,
    foundation_gate: Callable[[], str | None] | None,
    qualification_gate: Callable[[str], str | None] | None,
    expected_account: Callable[[], str | None] | None,
    load_environment_binding: Callable[..., Any] | None,
    read_private: Callable[[str], bytes] | None,
    root_source: Callable[[], Path] | None,
    security_of: Callable[[Path], Any] | None,
    declaration_dir: Path,
    launch_clients: Any | None,
    monotonic: Callable[[], float] | None,
    sleep: Callable[[float], None] | None,
) -> dict[str, Any]:
    """The injected seams, each the production one unless a test supplied its own."""
    import time

    return {
        "now": (lambda: datetime.now(tz=UTC)) if now is None else now,
        "client_factory": _client_factory if client_factory is None else client_factory,
        "caller_identity": _caller_identity if caller_identity is None else caller_identity,
        "foundation_gate": _foundation_gate if foundation_gate is None else foundation_gate,
        "qualification_gate": (
            _qualification_gate if qualification_gate is None else qualification_gate
        ),
        "expected_account": _expected_account if expected_account is None else expected_account,
        "load_environment_binding": (
            _load_environment_binding
            if load_environment_binding is None
            else load_environment_binding
        ),
        "read_private": _read_private if read_private is None else read_private,
        "root_source": root_source,
        "security_of": security_of,
        "declaration_dir": declaration_dir,
        "launch_clients": _launch_clients() if launch_clients is None else launch_clients,
        "monotonic": time.monotonic if monotonic is None else monotonic,
        "sleep": time.sleep if sleep is None else sleep,
    }


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    modules: Mapping[str, object] | None = None,
    now: Callable[[], datetime] | None = None,
    client_factory: Callable[[str, str], pc.PermissionClient] | None = None,
    caller_identity: Callable[[str], object] | None = None,
    foundation_gate: Callable[[], str | None] | None = None,
    qualification_gate: Callable[[str], str | None] | None = None,
    expected_account: Callable[[], str | None] | None = None,
    load_environment_binding: Callable[..., Any] | None = None,
    read_private: Callable[[str], bytes] | None = None,
    root_source: Callable[[], Path] | None = None,
    security_of: Callable[[Path], Any] | None = None,
    declaration_dir: Path = DECLARATION_DIR,
    launch_clients: Any | None = None,
    monotonic: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> int:
    """Plan (default), check a record, execute or complete one subcell, or run the cleanup."""
    import os

    arguments = list(sys.argv[1:] if argv is None else argv)
    for token in arguments:
        if token.split("=", 1)[0] in REFUSED_OPTIONS:
            print(SENTENCES["refused_arguments"])
            return EXIT_REFUSED_ARGUMENTS
    try:
        parsed = _parser().parse_args(arguments)
    except SystemExit:
        print(SENTENCES["refused_arguments"])
        return EXIT_REFUSED_ARGUMENTS
    rehearsal_mode = any(
        m is not None
        for m in (
            parsed.rehearse_deletion,
            parsed.prepare_rehearsal,
            parsed.collect_rehearsal_receipt,
            parsed.complete_rehearsal,
            parsed.recover_rehearsal_launch,
        )
    )
    if rehearsal_mode or parsed.rehearsal_inputs is not None:
        # The deletion rehearsal path (ADR-0049 s.3; proposed ADR-0050): implemented
        # offline, CLOSED until the governance decision (D-1) opens it. Refused before any
        # path or flag is read and before the rehearsal tool is imported.
        from kalpamani.data.production.sharadar.deletion_rehearsal import REHEARSAL_PATH_OPEN

        if not REHEARSAL_PATH_OPEN:
            print(SENTENCES["refused_rehearsal_closed"])
            return EXIT_REFUSED_REHEARSAL_CLOSED
        if not rehearsal_mode:
            print(SENTENCES["refused_arguments"])
            return EXIT_REFUSED_ARGUMENTS
        import production_deletion_rehearsal_tool as rehearsal

        return rehearsal.run(
            parsed,
            env=dict(os.environ) if env is None else dict(env),
            modules=modules,
            seams=_seams(
                now=now,
                client_factory=client_factory,
                caller_identity=caller_identity,
                foundation_gate=foundation_gate,
                qualification_gate=qualification_gate,
                expected_account=expected_account,
                load_environment_binding=load_environment_binding,
                read_private=read_private,
                root_source=root_source,
                security_of=security_of,
                declaration_dir=declaration_dir,
                launch_clients=launch_clients,
                monotonic=monotonic,
                sleep=sleep,
            ),
            cells=sys.modules[__name__],
        )
    modes = sum(
        (
            parsed.execute_subcell is not None,
            parsed.prepare_subcell is not None,
            parsed.complete_subcell is not None,
            parsed.recover_probe_launch is not None,
            parsed.collect_receipt is not None,
            parsed.cleanup,
            parsed.check_record is not None,
        )
    )
    if parsed.collection_authorized != (parsed.collect_receipt is not None):
        print(SENTENCES["refused_arguments"])
        return EXIT_REFUSED_ARGUMENTS
    if modes > 1 or (parsed.receipt_lines is not None and parsed.complete_subcell is None):
        print(SENTENCES["refused_arguments"])
        return EXIT_REFUSED_ARGUMENTS
    # An acknowledgement belongs to a hand-read completion only, and names a digest.
    if parsed.acknowledged_contradictions and (
        parsed.complete_subcell is None
        or parsed.receipt_lines is None
        or any(
            not isinstance(d, str) or _SHA256_RE.fullmatch(d) is None
            for d in parsed.acknowledged_contradictions
        )
    ):
        print(SENTENCES["refused_arguments"])
        return EXIT_REFUSED_ARGUMENTS
    if parsed.check_record is not None:
        try:
            record = pc.parse_permission_record(Path(parsed.check_record).read_bytes())
        except Exception:
            print(SENTENCES["check_refused"])
            return EXIT_CHECK_REFUSED
        for line in result_lines(record):
            print(line)
        print(SENTENCES["checked"])
        return EXIT_CHECKED
    if modes == 0:
        if parsed.authorized or parsed.cleanup_authorized:
            print(SENTENCES["refused_arguments"])
            return EXIT_REFUSED_ARGUMENTS
        try:
            lines = plan_lines(parsed.cell, parsed.subcell)
        except ValueError:
            print(SENTENCES["refused_arguments"])
            return EXIT_REFUSED_ARGUMENTS
        for line in lines:
            print(line)
        print(SENTENCES["planned"])
        return EXIT_PLANNED
    # An authorized mode: the paths, the flag that matches the mode, nothing else.
    if parsed.ledger is None or parsed.launch_inputs is None or parsed.records_dir is None:
        print(SENTENCES["refused_arguments"])
        return EXIT_REFUSED_ARGUMENTS
    if parsed.execute_subcell is not None and (
        not parsed.authorized or parsed.cleanup_authorized or parsed.authorization is None
    ):
        print(SENTENCES["refused_arguments"])
        return EXIT_REFUSED_ARGUMENTS
    if parsed.prepare_subcell is not None and (
        parsed.authorized or parsed.cleanup_authorized or parsed.authorization is not None
    ):
        print(SENTENCES["refused_arguments"])
        return EXIT_REFUSED_ARGUMENTS
    if parsed.cleanup and (not parsed.cleanup_authorized or parsed.authorized):
        print(SENTENCES["refused_arguments"])
        return EXIT_REFUSED_ARGUMENTS
    if parsed.complete_subcell is not None and (
        parsed.authorized
        or parsed.cleanup_authorized
        or parsed.authorization is not None
        or parsed.receipt_lines is None
    ):
        print(SENTENCES["refused_arguments"])
        return EXIT_REFUSED_ARGUMENTS
    if parsed.recover_probe_launch is not None and (
        parsed.authorized or parsed.cleanup_authorized or parsed.authorization is not None
    ):
        print(SENTENCES["refused_arguments"])
        return EXIT_REFUSED_ARGUMENTS
    if parsed.collect_receipt is not None and (
        parsed.authorized
        or parsed.cleanup_authorized
        or parsed.authorization is not None
        or parsed.receipt_lines is not None
    ):
        print(SENTENCES["refused_arguments"])
        return EXIT_REFUSED_ARGUMENTS
    environment = dict(os.environ) if env is None else dict(env)
    seams = _seams(
        now=now,
        client_factory=client_factory,
        caller_identity=caller_identity,
        foundation_gate=foundation_gate,
        qualification_gate=qualification_gate,
        expected_account=expected_account,
        load_environment_binding=load_environment_binding,
        read_private=read_private,
        root_source=root_source,
        security_of=security_of,
        declaration_dir=declaration_dir,
        launch_clients=launch_clients,
        monotonic=monotonic,
        sleep=sleep,
    )
    try:
        if parsed.prepare_subcell is not None:
            statement = prepare_subcell(
                parsed.prepare_subcell, parsed, env=environment, seams=seams
            )
            for line in statement_lines(statement):
                print(line)
            print(SENTENCES["prepared"])
            return EXIT_PREPARED
        if parsed.complete_subcell is not None:
            completed, _written = complete_subcell(
                parsed.complete_subcell, parsed, env=environment, seams=seams
            )
            for line in result_lines(completed):
                print(line)
            print(SENTENCES["completed"])
            return EXIT_COMPLETED
        if parsed.collect_receipt is not None:
            line = collect_receipt_for_subcell(
                parsed.collect_receipt,
                parsed,
                env=environment,
                modules=sys.modules if modules is None else modules,
                seams=seams,
            )
            completed, _written = complete_subcell(
                parsed.collect_receipt, parsed, env=environment, seams=seams, receipt_text=line
            )
            for line_ in result_lines(completed):
                print(line_)
            print(SENTENCES["completed"])
            return EXIT_COMPLETED
        if parsed.recover_probe_launch is not None:
            outcome = recover_probe_launch(
                parsed.recover_probe_launch, parsed, env=environment, seams=seams
            )
            print(f"recovered ledger_outcome={outcome}")
            print(SENTENCES["recovered"])
            return EXIT_RECOVERED
        if parsed.cleanup:
            cleanup = execute_cleanup(
                parsed,
                env=environment,
                modules=sys.modules if modules is None else modules,
                seams=seams,
            )
            for line in cleanup_lines(cleanup):
                print(line)
            if cleanup.residue or cleanup.budget_exhausted:
                print(SENTENCES["cleanup_unresolved"])
                return EXIT_CLEANUP_UNRESOLVED
            print(SENTENCES["cleaned"])
            return EXIT_EXECUTED
        executed = execute_subcell(
            parsed.execute_subcell,
            parsed,
            env=environment,
            modules=sys.modules if modules is None else modules,
            seams=seams,
        )
    except PermissionToolRefusalError as refusal:
        print(SENTENCES[refusal.key])
        return refusal.exit_code
    if isinstance(executed, ProbeLaunchResult):
        launched = executed
        print(
            f"probe launch={launched.report.outcome.value} "
            f"task_started={'yes' if launched.task_started else 'no'} "
            f"observed_exit_code={launched.report.observed_exit_code} "
            f"attempt_sha256={launched.attempt.digest}"
        )
        if launched.record is None:
            if not launched.task_started:
                print(SENTENCES["probe_not_started"])
                return EXIT_PROBE_NOT_STARTED
            print(SENTENCES["probe_launched"])
            return EXIT_PROBE_LAUNCHED
        record = launched.record
    else:
        record = executed
    for line in result_lines(record):
        print(line)
    if record.outcome is pc.SubcellOutcome.MATCHED:
        print(SENTENCES["executed"])
        return EXIT_EXECUTED
    if record.outcome is pc.SubcellOutcome.INVERTED:
        print(SENTENCES["inverted"])
        return EXIT_INVERTED
    print(SENTENCES["undecided"])
    return EXIT_UNDECIDED


__all__ = [
    "AUTHORIZATION_FLAG",
    "CLEANUP_FLAG",
    "CONSUMPTION_KIND",
    "DECLARATION_DIR",
    "REFUSED_OPTIONS",
    "SENTENCES",
    "TARGETS_ENV_VAR",
    "PermissionToolRefusalError",
    "ProbeLaunchResult",
    "complete_subcell",
    "current_binding",
    "declaration_paths",
    "execute_cleanup",
    "execute_subcell",
    "main",
    "permission_context",
    "plan_lines",
    "prepare_subcell",
    "prove_identity",
    "result_lines",
    "settlement_targets",
    "statement_lines",
]


if __name__ == "__main__":  # pragma: no cover - the owner's console entry
    sys.exit(main())
