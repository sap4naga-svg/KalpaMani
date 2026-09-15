"""The R-4 .. R-9 permission-subcell tool (ADR-0036 s.3; proposed ADR-0047). **Refuses by default.**

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

No AWS activity happens in this repository's tests; every result here is a counting
fake's. **Mocked results are not AWS verification.**
"""

from __future__ import annotations

import argparse
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
from kalpamani.data.production.sharadar import r3_verification as r3  # noqa: E402
from kalpamani.data.production.sharadar.vocabulary import (  # noqa: E402
    EXPECTED_PARTITION,
    EXPECTED_REGION,
    IdentityPath,
)
from kalpamani.data.qualify.sharadar.runtime_binding import (  # noqa: E402
    ENVIRONMENT_BINDING_ENV_VAR,
    QualificationEnvironmentBinding,
)

AUTHORIZATION_FLAG: Final = "--i-am-the-owner-authorizing-one-permission-subcell"
CLEANUP_FLAG: Final = "--i-am-the-owner-authorizing-permission-cleanup"
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
    if cell.layer is not pc.Layer.L3_RUNTIME:
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
) -> pc.PermissionRecord:
    """The authorized branch: one subcell, on injected seams."""
    if running_under_automation(env, modules):
        raise PermissionToolRefusalError(
            "refused_execution_context", EXIT_REFUSED_EXECUTION_CONTEXT
        )
    try:
        cell = pc.subcell(subcell_id)
    except ValueError:
        raise PermissionToolRefusalError("refused_subcell", EXIT_REFUSED_SUBCELL) from None
    if cell.layer is not pc.Layer.L3_RUNTIME:
        raise PermissionToolRefusalError("refused_subcell", EXIT_REFUSED_SUBCELL)
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
    for subcell_id, statements in evidence.statements.items():
        cell = pc.subcell(subcell_id)
        if cell.layer is not pc.Layer.L3_RUNTIME or not cell.requires:
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
                cell = pc.subcell(subcell_id)
                launch_target = admitted.resolve(cell, stamp=record.stamp, prerequisites={})
                assert launch_target.cluster_arn is not None
                tasks[record.attempt_sha256] = pc.TasksToSettle(
                    attempt_sha256=record.attempt_sha256,
                    started_by=record.started_by,
                    cluster_arn=launch_target.cluster_arn,
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
            if cell.operation in pc._LAUNCHING:
                launch_target = admitted.resolve(cell, stamp=attempt.stamp, prerequisites={})
                assert launch_target.cluster_arn is not None
                tasks[attempt.digest] = pc.TasksToSettle(
                    attempt_sha256=attempt.digest,
                    started_by=pc.started_by_of(attempt.stamp),
                    cluster_arn=launch_target.cluster_arn,
                    known_task_ids=(),
                )
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


class _Boto3PermissionClient:
    """Every permission operation over one profile's boto3 clients. One attempt each.

    ``total_max_attempts`` counts the initial request; every operation is exactly one
    transport attempt with finite connect and read timeouts. Each client is built lazily
    from the one session, so a subcell constructs only the service it uses.
    """

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
        self._clients: dict[str, Any] = {}

    @staticmethod
    def _profile_session(profile: str, region: str) -> Any:
        import boto3

        return boto3.Session(profile_name=profile, region_name=region)

    def _client(self, service: str) -> Any:
        if service not in self._clients:
            self._clients[service] = self._session.client(service, config=self._config)
        return self._clients[service]

    def _call(self, service: str, operation: str, **kwargs: Any) -> r3.Observation:
        from botocore.exceptions import (  # type: ignore[import-untyped]
            ClientError,
            ConnectTimeoutError,
            EndpointConnectionError,
            NoCredentialsError,
            ReadTimeoutError,
        )

        try:
            response = getattr(self._client(service), operation)(**kwargs)
        except ClientError as error:
            payload = error.response
            return r3.Observation(
                status=payload.get("ResponseMetadata", {}).get("HTTPStatusCode"),
                code=str(payload.get("Error", {}).get("Code", "")),
                message=str(payload.get("Error", {}).get("Message", "")),
            )
        except (ConnectTimeoutError, ReadTimeoutError):
            return r3.Observation(status=None, transport_failure="timeout")
        except EndpointConnectionError:
            return r3.Observation(status=None, transport_failure="network")
        except NoCredentialsError:
            return r3.Observation(status=None, code="NoCredentialsError")
        except Exception:
            return r3.Observation(status=None, code="Exception")
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if operation == "run_task":
            tasks = response.get("tasks") or []
            failures = response.get("failures") or []
            # Every returned task is accounted for, whatever the failure entries beside
            # it say: a task in the answer is a task that may be running. A 200 carrying
            # only failure entries started nothing it told us about; that is an
            # ambiguous launch (not a denial), and the cleanup lists by the tag.
            arns = tuple(
                str(task.get("taskArn", ""))
                for task in tasks[: pc.MAX_RETURNED_TASKS]
                if str(task.get("taskArn", ""))
            )
            if not arns:
                return r3.Observation(
                    status=None, code="RunTaskFailureEntry", failures=len(failures)
                )
            return r3.Observation(status=status, task_arns=arns, failures=len(failures))
        if operation == "list_tasks":
            arns = tuple(
                str(arn) for arn in (response.get("taskArns") or [])[: pc.MAX_RETURNED_TASKS]
            )
            token = response.get("nextToken")
            return r3.Observation(
                status=status,
                task_arns=arns,
                next_token=str(token) if isinstance(token, str) and token else None,
            )
        if operation == "describe_tasks":
            statuses = tuple(
                (str(task.get("taskArn", "")), str(task.get("lastStatus", "")))
                for task in (response.get("tasks") or [])[: pc.MAX_RETURNED_TASKS]
            )
            return r3.Observation(status=status, task_statuses=statuses)
        return r3.Observation(status=status)

    def put_object(
        self, bucket: str, key: str, body: bytes, *, if_none_match: bool
    ) -> r3.Observation:
        kwargs: dict[str, Any] = {"Bucket": bucket, "Key": key, "Body": body}
        if if_none_match:
            kwargs["IfNoneMatch"] = "*"
        return self._call("s3", "put_object", **kwargs)

    def get_object(self, bucket: str, key: str) -> r3.Observation:
        return self._call("s3", "get_object", Bucket=bucket, Key=key)

    def head_object(self, bucket: str, key: str) -> r3.Observation:
        return self._call("s3", "head_object", Bucket=bucket, Key=key)

    def delete_object(self, bucket: str, key: str) -> r3.Observation:
        return self._call("s3", "delete_object", Bucket=bucket, Key=key)

    def list_objects(self, bucket: str) -> r3.Observation:
        return self._call("s3", "list_objects_v2", Bucket=bucket, MaxKeys=1)

    def get_secret_value(self, secret_id: str) -> r3.Observation:
        # The value, if the service returns one, is never read: the response is
        # classified by status and dropped.
        return self._call("secretsmanager", "get_secret_value", SecretId=secret_id)

    def describe_secret(self, secret_id: str) -> r3.Observation:
        return self._call("secretsmanager", "describe_secret", SecretId=secret_id)

    def get_parameter(self, name: str) -> r3.Observation:
        return self._call("ssm", "get_parameter", Name=name, WithDecryption=True)

    def put_parameter(self, name: str, value: str) -> r3.Observation:
        return self._call(
            "ssm", "put_parameter", Name=name, Value=value, Type="String", Overwrite=False
        )

    def run_task(
        self,
        *,
        cluster_arn: str,
        task_definition_arn: str,
        task_role_arn: str | None,
        started_by: str,
        subnet_id: str,
        security_group_ids: tuple[str, ...],
        assign_public_ip: bool,
        platform_version: str,
    ) -> r3.Observation:
        # The same request shape the accepted launcher sends (compute.run_task_request):
        # FARGATE needs an awsvpc placement, and a request without one fails on its
        # parameters before any policy is evaluated -- not a permission test. The tag
        # lets the cleanup find a task an ambiguous answer may have started.
        kwargs: dict[str, Any] = {
            "cluster": cluster_arn,
            "taskDefinition": task_definition_arn,
            "count": 1,
            "launchType": "FARGATE",
            "platformVersion": platform_version,
            "networkConfiguration": {
                "awsvpcConfiguration": {
                    "subnets": [subnet_id],
                    "securityGroups": list(security_group_ids),
                    "assignPublicIp": "ENABLED" if assign_public_ip else "DISABLED",
                }
            },
            "enableExecuteCommand": False,
            "startedBy": started_by,
        }
        if task_role_arn is not None:
            kwargs["overrides"] = {"taskRoleArn": task_role_arn}
        return self._call("ecs", "run_task", **kwargs)

    def stop_task(self, *, cluster_arn: str, task_arn: str) -> r3.Observation:
        return self._call(
            "ecs",
            "stop_task",
            cluster=cluster_arn,
            task=task_arn,
            reason="kalpamani permission subcell: unexpected launch stopped",
        )

    def list_tasks(
        self, *, cluster_arn: str, started_by: str, next_token: str | None
    ) -> r3.Observation:
        # One page, filtered by startedBy and by nothing else: the ListTasks contract makes
        # startedBy the only filter when it is used (no desiredStatus, family, serviceName,
        # launchType or containerInstance beside it). The engine follows the token within
        # its bound.
        kwargs: dict[str, Any] = {
            "cluster": cluster_arn,
            "startedBy": started_by,
            "maxResults": pc.MAX_RETURNED_TASKS,
        }
        if next_token is not None:
            kwargs["nextToken"] = next_token
        return self._call("ecs", "list_tasks", **kwargs)

    def describe_tasks(self, *, cluster_arn: str, task_arns: tuple[str, ...]) -> r3.Observation:
        return self._call("ecs", "describe_tasks", cluster=cluster_arn, tasks=list(task_arns))

    def execute_command(self, *, cluster_arn: str, task_arn: str) -> r3.Observation:
        return self._call(
            "ecs",
            "execute_command",
            cluster=cluster_arn,
            task=task_arn,
            command="/bin/true",
            interactive=False,
        )


def _client_factory(profile: str, region: str) -> pc.PermissionClient:
    return _Boto3PermissionClient(profile, region)


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
) -> int:
    """Plan (default), check a record, execute one subcell, or run the cleanup."""
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
    modes = sum(
        (
            parsed.execute_subcell is not None,
            parsed.prepare_subcell is not None,
            parsed.cleanup,
            parsed.check_record is not None,
        )
    )
    if modes > 1:
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
    environment = dict(os.environ) if env is None else dict(env)
    seams: dict[str, Any] = {
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
    }
    try:
        if parsed.prepare_subcell is not None:
            statement = prepare_subcell(
                parsed.prepare_subcell, parsed, env=environment, seams=seams
            )
            for line in statement_lines(statement):
                print(line)
            print(SENTENCES["prepared"])
            return EXIT_PREPARED
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
        record = execute_subcell(
            parsed.execute_subcell,
            parsed,
            env=environment,
            modules=sys.modules if modules is None else modules,
            seams=seams,
        )
    except PermissionToolRefusalError as refusal:
        print(SENTENCES[refusal.key])
        return refusal.exit_code
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
