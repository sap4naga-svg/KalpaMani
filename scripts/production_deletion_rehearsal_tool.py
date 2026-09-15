"""The deletion rehearsal's owner modes of ``production_permission_cells`` (ADR-0049 s.3;
proposed ADR-0050): prepare a statement, launch the rehearsal task under the deletion
role, collect its receipt, complete the record.

Reached only through the permission tool's ``main``, and only once
``deletion_rehearsal.REHEARSAL_PATH_OPEN`` is True: while the path is CLOSED the
permission tool refuses every rehearsal mode before this module is imported, before any
path or flag is read and before any client exists. Nothing here is executed today.

The four modes, in the order an owner runs them::

    --prepare-rehearsal <R8 subcell>                       (no flag; writes the statement)
    --rehearse-deletion <R8 subcell> --rehearsal-inputs F --authorization A <AUTHORIZATION_FLAG>
    --collect-rehearsal-receipt <R8 subcell> --rehearsal-inputs F <COLLECT_FLAG>
    --complete-rehearsal <R8 subcell> --receipt-lines L    (no flag; offline)

Every step reuses what the permission tool already admits and proves: the bindings, the
registration, the targets, the evidence, the store's durable authorization consumption,
the record naming, the collector and its one admission rule. What is the rehearsal's own
-- the statement, the launch inputs, the launcher's identity, the launch sequence, the
task receipt and the completion -- lives in ``deletion_rehearsal_launch`` and
``deletion_rehearsal_task``, and is exercised here through the same seams a test injects.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Final

#: Exit codes of this module's own outcomes; every other exit reuses the permission
#: tool's (identity 4, binding 5, dependency 7, record write 8, inverted 9, undecided 10,
#: cleanup unresolved 12, subcell 13, preparation 14, authorization 15, consumed 16,
#: prerequisite 17, completion 19, collection 25/28/29/30).
EXIT_REHEARSAL_LAUNCHED: Final = 0
EXIT_REHEARSAL_NOT_LAUNCHED: Final = 31
EXIT_REFUSED_REHEARSAL_RECORDS: Final = 32

SENTENCES: Final[dict[str, str]] = {
    "rehearsal_prepared": (
        "deletion rehearsal statement written; nothing was performed (authorize its digest)"
    ),
    "rehearsal_launched": (
        "deletion rehearsal launched and observed to its terminal state; complete the subcell "
        "from its receipt (--collect-rehearsal-receipt, or --complete-rehearsal --receipt-lines)"
    ),
    "rehearsal_not_launched": (
        "deletion rehearsal not launched: the outcome and counts are recorded, the "
        "authorization is consumed where the sequence reached consumption, and nothing is "
        "retried (prepare and authorize again)"
    ),
    "rehearsal_passed": (
        "deletion rehearsal PASSED: the record was written and the control principal's "
        "later verified cleanup settles the object"
    ),
    "rehearsal_failed": (
        "deletion rehearsal FAILED: the deletion role's observed answer contradicts the "
        "expectation; the record was written"
    ),
    "rehearsal_undecided": (
        "deletion rehearsal INCONCLUSIVE: the answer decided nothing; the record was written "
        "and nothing is re-executed here"
    ),
    "rehearsal_cleanup_unresolved": (
        "deletion rehearsal recorded; the removal is not yet confirmed by a later verified "
        "cleanup naming the exact key (CLEANUP_UNRESOLVED or RESIDUE)"
    ),
    "refused_rehearsal_records": (
        "permission cells refused: a rehearsal statement, launch record or record under the "
        "records directory is malformed; nothing is chosen between them"
    ),
    "refused_rehearsal_inputs": (
        "permission cells refused: the rehearsal launch inputs were not admitted (not the "
        "rehearsal family, not the deletion role, another account, or not the bound one)"
    ),
}

_STATEMENT_PREFIX: Final = "rehearsal-statement"
_LAUNCH_PREFIX: Final = "rehearsal-launch-record"
_RECORD_PREFIX: Final = "rehearsal-record"


class _RehearsalEvidence:
    """Every rehearsal statement, launch record and record under the records directory,
    each parsed closed; a malformed one refuses the whole reading."""

    __slots__ = ("launches", "records", "statements")

    def __init__(self, records_dir: Path, cells: Any) -> None:
        from kalpamani.data.production.sharadar import deletion_rehearsal as dr
        from kalpamani.data.production.sharadar import deletion_rehearsal_launch as dl
        from kalpamani.data.production.sharadar import deletion_rehearsal_task as dt

        self.statements: list[Any] = []
        self.launches: list[Any] = []
        self.records: list[Any] = []
        try:
            for path in sorted(records_dir.glob(f"{_STATEMENT_PREFIX}-*.json")):
                self.statements.append(dt.parse_rehearsal_statement(path.read_bytes()))
            for path in sorted(records_dir.glob(f"{_LAUNCH_PREFIX}-*.json")):
                self.launches.append(dl.parse_rehearsal_launch_record(path.read_bytes()))
            for path in sorted(records_dir.glob(f"{_RECORD_PREFIX}-*.json")):
                self.records.append(dr.parse_rehearsal_record(path.read_bytes()))
        except Exception:
            raise cells.PermissionToolRefusalError(
                "refused_rehearsal_records", EXIT_REFUSED_REHEARSAL_RECORDS
            ) from None

    def earlier(self, binding: Any) -> tuple[str, ...]:
        """The rehearsal subcells recorded PASS with a verified identity under ``binding``:
        what :func:`prepare_rehearsal` needs to admit the next subcell of the sequence."""
        from kalpamani.data.production.sharadar.deletion_rehearsal import RehearsalOutcome

        return tuple(
            sorted(
                {
                    r.subcell_id
                    for r in self.records
                    if r.binding == binding
                    and r.outcome is RehearsalOutcome.PASS
                    and r.identity_verified
                }
            )
        )

    def pending_launch(self, subcell_id: str, binding: Any) -> Any:
        """The one LAUNCHED, terminal launch of ``subcell_id`` under ``binding`` that no
        rehearsal record completes yet, or ``None``."""
        from kalpamani.data.production.sharadar.deletion_rehearsal_launch import (
            RehearsalLaunchOutcome,
        )

        completed = {(r.statement_sha256, r.authorization_sha256) for r in self.records}
        pending = [
            launch
            for launch in self.launches
            if launch.subcell_id == subcell_id
            and launch.binding == binding
            and launch.outcome is RehearsalLaunchOutcome.LAUNCHED
            and launch.observed_exit_code is not None
            and (launch.statement_sha256, launch.authorization_sha256) not in completed
        ]
        return pending[0] if len(pending) == 1 else None


def _subcell(subcell_id: str, cells: Any) -> None:
    from kalpamani.data.production.sharadar.deletion_rehearsal import REHEARSAL_SEQUENCE

    if subcell_id not in REHEARSAL_SEQUENCE:
        raise cells.PermissionToolRefusalError("refused_subcell", cells.EXIT_REFUSED_SUBCELL)


def _admitted(
    parsed: argparse.Namespace, env: Mapping[str, str], seams: dict[str, Any], cells: Any
) -> tuple[Any, Any, _RehearsalEvidence]:
    admitted = cells._admit(
        parsed,
        env,
        expected_account=seams["expected_account"],
        load_environment_binding=seams["load_environment_binding"],
        read_private=seams["read_private"],
        declaration_dir=seams.get("declaration_dir", cells.DECLARATION_DIR),
        root_source=seams.get("root_source"),
    )
    evidence = cells._evidence(admitted)
    rehearsal = _RehearsalEvidence(admitted.store._records_dir, cells)
    return admitted, evidence, rehearsal


def _recomputed_statement(
    subcell_id: str,
    stamp: str,
    statement_sha256: str,
    *,
    evidence: Any,
    rehearsal: _RehearsalEvidence,
    binding: Any,
    cells: Any,
) -> Any:
    """The statement ``statement_sha256`` names, recomputed from ``stamp`` against what is
    admitted NOW -- the bindings, the R-4 record, the earlier rehearsal records -- and held
    to the prepared digest byte for byte."""
    from kalpamani.data.production.sharadar.deletion_rehearsal import (
        RehearsalError,
        prepare_rehearsal,
    )

    try:
        statement = prepare_rehearsal(
            subcell_id, evidence, stamp=stamp, earlier=rehearsal.earlier(binding)
        )
    except RehearsalError:
        raise cells.PermissionToolRefusalError(
            "refused_prerequisite", cells.EXIT_REFUSED_PREREQUISITE
        ) from None
    if statement.digest != statement_sha256 or statement.binding != binding:
        raise cells.PermissionToolRefusalError(
            "refused_preparation", cells.EXIT_REFUSED_PREPARATION
        )
    return statement


def _rehearsal_inputs(parsed: argparse.Namespace, admitted: Any, cells: Any) -> Any:
    """The registered rehearsal launch inputs, parsed closed and held to the bound account."""
    from kalpamani.data.production.sharadar.deletion_rehearsal_launch import (
        parse_rehearsal_launch_inputs,
    )
    from kalpamani.data.production.sharadar.launch_records import MAX_RECORD_BYTES

    try:
        raw = Path(parsed.rehearsal_inputs).read_bytes()
        if len(raw) > MAX_RECORD_BYTES:
            raise ValueError("oversize")
        inputs = parse_rehearsal_launch_inputs(raw)
    except Exception:
        raise cells.PermissionToolRefusalError(
            "refused_rehearsal_inputs", cells.EXIT_REFUSED_BINDING
        ) from None
    if inputs.account != admitted.environment.target_account_id:
        raise cells.PermissionToolRefusalError(
            "refused_rehearsal_inputs", cells.EXIT_REFUSED_BINDING
        )
    return inputs


def _launcher_identity(
    env: Mapping[str, str], seams: dict[str, Any], cells: Any
) -> Callable[[], Any]:
    """The rehearsal launcher's caller-identity call under its one profile, or refuse."""
    from kalpamani.data.production.sharadar.deletion_rehearsal import REHEARSAL_LAUNCHER_PROFILE

    if env.get("AWS_PROFILE", "") != REHEARSAL_LAUNCHER_PROFILE:
        raise cells.PermissionToolRefusalError("refused_identity", cells.EXIT_REFUSED_IDENTITY)
    launch_clients = seams["launch_clients"]

    def call() -> Any:
        return launch_clients.sts(REHEARSAL_LAUNCHER_PROFILE).get_caller_identity()

    return call


def _prerequisite_attempt(statement: Any, evidence: Any, binding: Any) -> str | None:
    """The R-4 attempt that created the statement's target: what a cleanup pass names."""
    from kalpamani.data.production.sharadar.deletion_rehearsal import REHEARSAL_PREREQUISITE

    for record in evidence.records.get(REHEARSAL_PREREQUISITE, ()):
        if (
            record.binding == binding
            and record.created_bucket == statement.target.bucket
            and record.created_key == statement.target.key
        ):
            return str(record.attempt_sha256)
    return None


# ---------------------------------------------------------------------------
# The modes
# ---------------------------------------------------------------------------


def prepare(
    subcell_id: str,
    parsed: argparse.Namespace,
    *,
    env: Mapping[str, str],
    seams: dict[str, Any],
    cells: Any,
) -> int:
    """Write the statement of one rehearsal: the exact synthetic target, the position in
    the sequence, the stamp, the binding. No identity proof and no client."""
    from kalpamani.data.production.sharadar import r3_verification as r3
    from kalpamani.data.production.sharadar.deletion_rehearsal import (
        RehearsalError,
        prepare_rehearsal,
    )

    _subcell(subcell_id, cells)
    now: Callable[[], datetime] = seams["now"]
    admitted, evidence, rehearsal = _admitted(parsed, env, seams, cells)
    try:
        statement = prepare_rehearsal(
            subcell_id,
            evidence,
            stamp=r3.new_stamp(now()),
            earlier=rehearsal.earlier(admitted.binding),
        )
    except RehearsalError:
        raise cells.PermissionToolRefusalError(
            "refused_prerequisite", cells.EXIT_REFUSED_PREREQUISITE
        ) from None
    try:
        admitted.store.write_record(_STATEMENT_PREFIX, statement.document(), at=now())
    except Exception:
        raise cells.PermissionToolRefusalError(
            "refused_record_write", cells.EXIT_REFUSED_RECORD_WRITE
        ) from None
    print(
        f"rehearsal statement subcell={statement.subcell_id} "
        f"principal=deletion_role sequence_position={statement.document()['sequence_position']} "
        f"stamp={statement.stamp} target_sha256={statement.target.digest}"
    )
    print(f"statement_sha256={statement.digest}")
    print(SENTENCES["rehearsal_prepared"])
    return int(cells.EXIT_PREPARED)


def rehearse(
    subcell_id: str,
    parsed: argparse.Namespace,
    *,
    env: Mapping[str, str],
    modules: Mapping[str, object],
    seams: dict[str, Any],
    cells: Any,
) -> int:
    """Launch the rehearsal task for one authorized statement and observe it.

    The owner's authorization names the prepared statement; the statement is recomputed
    against what is admitted now; the rehearsal launch inputs are held to the rehearsal
    family, the deletion role and the bound account; the launcher's identity is the
    generated role of ``KalpaManiDeletionRehearse`` under its one profile. The sequence
    (:func:`launch_rehearsal`) consumes the authorization durably before it mutates
    anything, reserves beside the ledger, materializes the input, runs one ``RunTask``
    (never retried), verifies placement, releases, observes to the terminal state and
    records what it observed. The task's own operations happen inside the task under the
    deletion role; nothing here issues a data operation.
    """
    from kalpamani.data.production.sharadar.compute import Ec2InterfaceAdapter
    from kalpamani.data.production.sharadar.deletion_rehearsal import (
        REHEARSAL_LAUNCHER_PROFILE,
    )
    from kalpamani.data.production.sharadar.deletion_rehearsal_launch import (
        CompiledRehearsalLaunch,
        RehearsalEcs,
        RehearsalLaunchAdapters,
        RehearsalLaunchError,
        RehearsalLaunchOutcome,
        launch_rehearsal,
        rehearsal_launcher_identity_verified,
    )
    from kalpamani.data.production.sharadar.launch_records import MAX_RECORD_BYTES
    from kalpamani.data.production.sharadar.parameters import SsmParameterAdapter
    from kalpamani.data.production.sharadar.permission_cells import (
        parse_permission_authorization,
    )

    if cells.running_under_automation(env, modules):
        raise cells.PermissionToolRefusalError(
            "refused_execution_context", cells.EXIT_REFUSED_EXECUTION_CONTEXT
        )
    _subcell(subcell_id, cells)
    now: Callable[[], datetime] = seams["now"]
    admitted, evidence, rehearsal = _admitted(parsed, env, seams, cells)
    inputs = _rehearsal_inputs(parsed, admitted, cells)
    try:
        raw = Path(parsed.authorization).read_bytes()
        if len(raw) > MAX_RECORD_BYTES:
            raise ValueError("oversize")
        authorization = parse_permission_authorization(
            raw, subcell_id=subcell_id, statement_sha256=None, now=now()
        )
    except Exception:
        raise cells.PermissionToolRefusalError(
            "refused_authorization", cells.EXIT_REFUSED_AUTHORIZATION
        ) from None
    prepared = [
        s
        for s in rehearsal.statements
        if s.subcell_id == subcell_id
        and s.binding == admitted.binding
        and s.digest == authorization.statement_sha256
    ]
    if len(prepared) != 1:
        raise cells.PermissionToolRefusalError(
            "refused_preparation", cells.EXIT_REFUSED_PREPARATION
        )
    statement = _recomputed_statement(
        subcell_id,
        prepared[0].stamp,
        authorization.statement_sha256,
        evidence=evidence,
        rehearsal=rehearsal,
        binding=admitted.binding,
        cells=cells,
    )
    if rehearsal.pending_launch(subcell_id, admitted.binding) is not None:
        # A launched, uncompleted rehearsal of this subcell is completed before another
        # is launched: the receipt it produced is evidence, and it is never repeated over.
        raise cells.PermissionToolRefusalError("refused_completion", cells.EXIT_REFUSED_COMPLETION)
    # Identity before any other client exists: the launcher's generated role in the bound
    # account, under its one profile; the sequence proves it again before it consumes.
    caller_identity = _launcher_identity(env, seams, cells)
    try:
        caller = caller_identity()
    except Exception:
        raise cells.PermissionToolRefusalError(
            "refused_identity", cells.EXIT_REFUSED_IDENTITY
        ) from None
    if not rehearsal_launcher_identity_verified(caller, account=inputs.account):
        raise cells.PermissionToolRefusalError("refused_identity", cells.EXIT_REFUSED_IDENTITY)
    launch_clients = seams["launch_clients"]
    try:
        compiled = CompiledRehearsalLaunch(inputs=inputs, stamp=statement.stamp)
    except RehearsalLaunchError:
        raise cells.PermissionToolRefusalError(
            "refused_rehearsal_inputs", cells.EXIT_REFUSED_BINDING
        ) from None
    try:
        adapters = RehearsalLaunchAdapters(
            ecs=RehearsalEcs(ecs=launch_clients.ecs(REHEARSAL_LAUNCHER_PROFILE), compiled=compiled),
            ec2=Ec2InterfaceAdapter(ec2=launch_clients.ec2(REHEARSAL_LAUNCHER_PROFILE)),
            parameters=SsmParameterAdapter(ssm=launch_clients.ssm(REHEARSAL_LAUNCHER_PROFILE)),
        )
    except Exception:
        raise cells.PermissionToolRefusalError(
            "refused_dependency", cells.EXIT_REFUSED_DEPENDENCY
        ) from None
    report = launch_rehearsal(
        statement,
        authorization_sha256=authorization.digest,
        authorization_document=authorization.document(),
        store=admitted.store,
        compiled=compiled,
        adapters=adapters,
        caller_identity=caller_identity,
        now=now,
        monotonic=seams["monotonic"],
        sleep=seams["sleep"],
    )
    print(
        f"rehearsal launch={report.outcome.value} subcell={subcell_id} "
        f"run_tasks={report.run_tasks} describes={report.describes} stops={report.stops} "
        f"parameter_puts={report.parameter_puts} parameter_deletes={report.parameter_deletes} "
        f"cleanup_failures={list(report.cleanup_failures)}"
    )
    if report.record is not None:
        print(
            f"rehearsal_launch_record_digest={report.record.digest} "
            f"observed_exit_code={report.record.observed_exit_code}"
        )
    if report.outcome is RehearsalLaunchOutcome.REFUSED_IDENTITY:
        raise cells.PermissionToolRefusalError("refused_identity", cells.EXIT_REFUSED_IDENTITY)
    if report.outcome is RehearsalLaunchOutcome.REFUSED_CONSUMED:
        raise cells.PermissionToolRefusalError(
            "refused_authorization_consumed", cells.EXIT_REFUSED_AUTHORIZATION_CONSUMED
        )
    if report.outcome is RehearsalLaunchOutcome.LAUNCHED:
        print(SENTENCES["rehearsal_launched"])
        return EXIT_REHEARSAL_LAUNCHED
    print(SENTENCES["rehearsal_not_launched"])
    return EXIT_REHEARSAL_NOT_LAUNCHED


def collect(
    subcell_id: str,
    parsed: argparse.Namespace,
    *,
    env: Mapping[str, str],
    modules: Mapping[str, object],
    seams: dict[str, Any],
    cells: Any,
) -> int:
    """Collect the rehearsal task's receipt line from its own stream, then complete.

    The same collector, the same bounds and the same admission rule as a probe receipt
    (ADR-0049 s.2), with the rehearsal receipt's verifier bound to the launch record's
    expectation; the destination is the registered rehearsal log destination; the reader
    is the rehearsal launcher under its one profile. The line completes the subcell
    exactly as a hand-read one does.
    """
    from kalpamani.data.production.sharadar.deletion_rehearsal import (
        REHEARSAL_LAUNCHER_PROFILE,
    )
    from kalpamani.data.production.sharadar.deletion_rehearsal_launch import (
        rehearsal_launcher_identity_verified,
    )
    from kalpamani.data.production.sharadar.deletion_rehearsal_task import (
        rehearsal_receipt_verifier,
    )
    from kalpamani.data.production.sharadar.launch_store import StoreError
    from kalpamani.data.production.sharadar.receipt_collector import (
        CollectionRecordDefect,
        CollectionRecordError,
        SdkLogsClient,
        admit_collection_records,
        collect_receipt,
    )
    from kalpamani.data.production.sharadar.receipts import decode_receipt_line

    if cells.running_under_automation(env, modules):
        raise cells.PermissionToolRefusalError(
            "refused_execution_context", cells.EXIT_REFUSED_EXECUTION_CONTEXT
        )
    _subcell(subcell_id, cells)
    now: Callable[[], datetime] = seams["now"]
    admitted, evidence, rehearsal = _admitted(parsed, env, seams, cells)
    inputs = _rehearsal_inputs(parsed, admitted, cells)
    launch = rehearsal.pending_launch(subcell_id, admitted.binding)
    if launch is None or launch.task_definition_arn != inputs.task_definition_arn:
        raise cells.PermissionToolRefusalError("refused_completion", cells.EXIT_REFUSED_COMPLETION)
    expectation = launch.expectation()
    verify = rehearsal_receipt_verifier(expectation)
    destination = inputs.log_destination
    try:
        admission = admit_collection_records(
            cells._collection_payloads(admitted.store._records_dir),
            identity=launch.identity,
            launch_record_sha256=launch.digest,
            destination=destination,
            task_id=launch.task_id,
            verify=verify,
        )
    except CollectionRecordError as error:
        if error.defect is CollectionRecordDefect.CONTRADICTION_UNRESOLVED:
            raise cells.PermissionToolRefusalError(
                "refused_contradiction_unresolved", cells.EXIT_REFUSED_CONTRADICTION_UNRESOLVED
            ) from None
        if error.defect is CollectionRecordDefect.RECEIPT_SUBSTITUTED:
            raise cells.PermissionToolRefusalError(
                "refused_receipt_binding", cells.EXIT_REFUSED_RECEIPT_BINDING
            ) from None
        raise cells.PermissionToolRefusalError(
            "refused_collection_records", cells.EXIT_REFUSED_COLLECTION_RECORDS
        ) from None
    except OSError:
        raise cells.PermissionToolRefusalError(
            "refused_collection_records", cells.EXIT_REFUSED_COLLECTION_RECORDS
        ) from None
    line = admission.reusable_line
    if line is None:
        if admission.bound_receipt_sha256 is not None:
            raise cells.PermissionToolRefusalError(
                "refused_receipt_binding", cells.EXIT_REFUSED_RECEIPT_BINDING
            )
        caller_identity = _launcher_identity(env, seams, cells)
        try:
            caller = caller_identity()
        except Exception:
            raise cells.PermissionToolRefusalError(
                "refused_identity", cells.EXIT_REFUSED_IDENTITY
            ) from None
        if not rehearsal_launcher_identity_verified(
            caller, account=admitted.environment.target_account_id
        ):
            raise cells.PermissionToolRefusalError("refused_identity", cells.EXIT_REFUSED_IDENTITY)
        launch_clients = seams["launch_clients"]
        try:
            client = SdkLogsClient(lambda _service: launch_clients.logs(REHEARSAL_LAUNCHER_PROFILE))
        except Exception:
            raise cells.PermissionToolRefusalError(
                "refused_dependency", cells.EXIT_REFUSED_DEPENDENCY
            ) from None
        collected = collect_receipt(
            destination=destination,
            task_id=launch.task_id,
            verify=verify,
            client=client,
            now=now,
            monotonic=seams["monotonic"],
            sleep=seams["sleep"],
        )
        try:
            admitted.store.write_record(
                "receipt-collection",
                collected.document(identity=launch.identity, launch_record_sha256=launch.digest),
                at=collected.finished_at,
            )
        except StoreError:
            raise cells.PermissionToolRefusalError(
                "refused_record_write", cells.EXIT_REFUSED_RECORD_WRITE
            ) from None
        print(collected.summary())
        if collected.receipt_line is None:
            raise cells.PermissionToolRefusalError(
                "collection_not_collected", cells.EXIT_COLLECTION_NOT_COLLECTED
            )
        line = collected.receipt_line
    return _complete(
        launch, decode_receipt_line(line), admitted, evidence, rehearsal, now=now, cells=cells
    )


def complete(
    subcell_id: str,
    parsed: argparse.Namespace,
    *,
    env: Mapping[str, str],
    seams: dict[str, Any],
    cells: Any,
) -> int:
    """Complete a launched rehearsal from its hand-read receipt lines. Offline; no client."""
    from kalpamani.data.production.sharadar.deletion_rehearsal_task import (
        receipt_lines_within,
    )
    from kalpamani.data.production.sharadar.receipts import (
        MAX_RECEIPT_BYTES,
        ReceiptError,
        decode_receipt_line,
    )

    _subcell(subcell_id, cells)
    now: Callable[[], datetime] = seams["now"]
    admitted, evidence, rehearsal = _admitted(parsed, env, seams, cells)
    launch = rehearsal.pending_launch(subcell_id, admitted.binding)
    if launch is None:
        raise cells.PermissionToolRefusalError("refused_completion", cells.EXIT_REFUSED_COMPLETION)
    try:
        raw = Path(parsed.receipt_lines).read_bytes()
        if len(raw) > 64 * MAX_RECEIPT_BYTES:
            raise ValueError("oversize")
        lines = receipt_lines_within(raw.decode("utf-8").splitlines())
        if len(lines) != 1:
            raise ValueError("exactly one receipt line")
        document = decode_receipt_line(lines[0])
    except (OSError, ValueError, UnicodeDecodeError, ReceiptError):
        raise cells.PermissionToolRefusalError(
            "refused_completion", cells.EXIT_REFUSED_COMPLETION
        ) from None
    return _complete(launch, document, admitted, evidence, rehearsal, now=now, cells=cells)


def _complete(
    launch: Any,
    document: object,
    admitted: Any,
    evidence: Any,
    rehearsal: _RehearsalEvidence,
    *,
    now: Callable[[], datetime],
    cells: Any,
) -> int:
    """The rehearsal record from the verified receipt, written; then the reading with the
    control principal's cleanups -- the derived status, never a supplied one."""
    from kalpamani.data.production.sharadar.deletion_rehearsal import (
        RehearsalStatus,
        derive_rehearsal,
    )
    from kalpamani.data.production.sharadar.deletion_rehearsal_launch import (
        RehearsalCompletionError,
        complete_rehearsal,
    )
    from kalpamani.data.production.sharadar.deletion_rehearsal_task import (
        REHEARSAL_IDENTITY_PREFIX,
    )

    stamp = launch.identity[len(REHEARSAL_IDENTITY_PREFIX) :]
    statement = _recomputed_statement(
        launch.subcell_id,
        stamp,
        launch.statement_sha256,
        evidence=evidence,
        rehearsal=rehearsal,
        binding=admitted.binding,
        cells=cells,
    )
    try:
        record = complete_rehearsal(launch, document, statement=statement)
    except RehearsalCompletionError as error:
        print(f"rehearsal completion refused: {error.defect.value}")
        raise cells.PermissionToolRefusalError(
            "refused_completion", cells.EXIT_REFUSED_COMPLETION
        ) from None
    try:
        admitted.store.write_record(_RECORD_PREFIX, record.document(), at=now())
    except Exception:
        raise cells.PermissionToolRefusalError(
            "refused_record_write", cells.EXIT_REFUSED_RECORD_WRITE
        ) from None
    prerequisite_attempt = _prerequisite_attempt(statement, evidence, admitted.binding)
    if prerequisite_attempt is None:
        status, reason = RehearsalStatus.INCONCLUSIVE, "the prerequisite attempt is not bound"
    else:
        status, reason = derive_rehearsal(
            record, evidence.cleanups, prerequisite_attempt=prerequisite_attempt
        )
    print(
        f"rehearsal subcell={record.subcell_id} outcome={record.outcome.value} "
        f"observed={[o.value for o in record.observed]} "
        f"deleted={'yes' if record.deleted else 'no'} "
        f"possibly_deleted={'yes' if record.possibly_deleted else 'no'} "
        f"operations={record.operations} "
        f"identity_verified={'yes' if record.identity_verified else 'no'} "
        f"status={status.value} reason={reason}"
    )
    print(f"rehearsal_record_digest={record.digest}")
    if status is RehearsalStatus.PASSED:
        print(SENTENCES["rehearsal_passed"])
        return int(cells.EXIT_EXECUTED)
    if status is RehearsalStatus.FAILED:
        print(SENTENCES["rehearsal_failed"])
        return int(cells.EXIT_INVERTED)
    if status is RehearsalStatus.INCONCLUSIVE:
        print(SENTENCES["rehearsal_undecided"])
        return int(cells.EXIT_UNDECIDED)
    print(SENTENCES["rehearsal_cleanup_unresolved"])
    return int(cells.EXIT_CLEANUP_UNRESOLVED)


# ---------------------------------------------------------------------------
# Entry from the permission tool
# ---------------------------------------------------------------------------


def _arguments_admitted(parsed: argparse.Namespace, cells: Any) -> bool:
    """Exactly one rehearsal mode, with exactly the flags and paths that mode takes."""
    modes = [
        parsed.prepare_rehearsal is not None,
        parsed.rehearse_deletion is not None,
        parsed.collect_rehearsal_receipt is not None,
        parsed.complete_rehearsal is not None,
    ]
    if sum(modes) != 1:
        return False
    other_modes = (
        parsed.execute_subcell,
        parsed.prepare_subcell,
        parsed.complete_subcell,
        parsed.recover_probe_launch,
        parsed.collect_receipt,
        parsed.check_record,
    )
    if any(m is not None for m in other_modes) or parsed.cleanup or parsed.cleanup_authorized:
        return False
    if parsed.acknowledged_contradictions:
        return False
    if parsed.ledger is None or parsed.launch_inputs is None or parsed.records_dir is None:
        return False
    if parsed.prepare_rehearsal is not None:
        return not (
            parsed.authorized
            or parsed.collection_authorized
            or parsed.authorization is not None
            or parsed.receipt_lines is not None
            or parsed.rehearsal_inputs is not None
        )
    if parsed.rehearse_deletion is not None:
        return (
            parsed.authorized
            and not parsed.collection_authorized
            and parsed.authorization is not None
            and parsed.rehearsal_inputs is not None
            and parsed.receipt_lines is None
        )
    if parsed.collect_rehearsal_receipt is not None:
        return (
            parsed.collection_authorized
            and not parsed.authorized
            and parsed.authorization is None
            and parsed.rehearsal_inputs is not None
            and parsed.receipt_lines is None
        )
    return (
        not parsed.authorized
        and not parsed.collection_authorized
        and parsed.authorization is None
        and parsed.rehearsal_inputs is None
        and parsed.receipt_lines is not None
    )


def run(
    parsed: argparse.Namespace,
    *,
    env: Mapping[str, str],
    modules: Mapping[str, object] | None,
    seams: dict[str, Any],
    cells: Any,
) -> int:
    """One rehearsal mode; the permission tool has already established the path is OPEN."""
    if not _arguments_admitted(parsed, cells):
        print(cells.SENTENCES["refused_arguments"])
        return int(cells.EXIT_REFUSED_ARGUMENTS)
    module_table = sys.modules if modules is None else modules
    try:
        if parsed.prepare_rehearsal is not None:
            return prepare(parsed.prepare_rehearsal, parsed, env=env, seams=seams, cells=cells)
        if parsed.rehearse_deletion is not None:
            return rehearse(
                parsed.rehearse_deletion,
                parsed,
                env=env,
                modules=module_table,
                seams=seams,
                cells=cells,
            )
        if parsed.collect_rehearsal_receipt is not None:
            return collect(
                parsed.collect_rehearsal_receipt,
                parsed,
                env=env,
                modules=module_table,
                seams=seams,
                cells=cells,
            )
        return complete(parsed.complete_rehearsal, parsed, env=env, seams=seams, cells=cells)
    except cells.PermissionToolRefusalError as refusal:
        print(SENTENCES.get(refusal.key) or cells.SENTENCES[refusal.key])
        return int(refusal.exit_code)


__all__ = [
    "EXIT_REFUSED_REHEARSAL_RECORDS",
    "EXIT_REHEARSAL_LAUNCHED",
    "EXIT_REHEARSAL_NOT_LAUNCHED",
    "SENTENCES",
    "collect",
    "complete",
    "prepare",
    "rehearse",
    "run",
]
