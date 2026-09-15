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
    --recover-rehearsal-launch <R8 subcell>                (no flag; offline; after an interruption)

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
    "rehearsal_recovered": (
        "interrupted deletion rehearsal launch recorded RECOVERED_INTERRUPTED beside the ledger; "
        "nothing was launched or retried; whether a task started is UNKNOWN until the control "
        "principal's cleanup lists the reservation's tag and confirms every task stopped"
    ),
    "refused_rehearsal_recovery": (
        "permission cells refused: no interrupted (reserved, unresolved) rehearsal launch of this "
        "subcell beside the ledger"
    ),
    "refused_rehearsal_recovery_pending": (
        "permission cells refused: an earlier rehearsal reservation beside the ledger is unsettled "
        "-- interrupted (recover it with --recover-rehearsal-launch) or its task not yet confirmed "
        "stopped by a verified cleanup -- so no rehearsal is launched, under any authorization or "
        "from any records directory, until it is"
    ),
    "refused_rehearsal_reserved": (
        "permission cells refused: this rehearsal identity is already reserved beside the ledger; "
        "the authorization is consumed and nothing was launched (prepare and authorize again)"
    ),
    "rehearsal_completion_recorded": (
        "deletion rehearsal already completed from this receipt; the record and the retained "
        "receipt are present and nothing was changed"
    ),
    "refused_rehearsal_inputs": (
        "permission cells refused: the rehearsal launch inputs were not admitted (not the "
        "rehearsal family, not the deletion role, another account, or not the bound one)"
    ),
}

_STATEMENT_PREFIX: Final = "rehearsal-statement"
_LAUNCH_PREFIX: Final = "rehearsal-launch-record"
_RECORD_PREFIX: Final = "rehearsal-record"
_RECEIPT_PREFIX: Final = "rehearsal-receipt"


class _RehearsalEvidence:
    """Every rehearsal statement, launch record, record and retained receipt under the
    records directory, plus every reservation and resolution anchored beside the canonical
    ledger and every consumed rehearsal authorization -- each parsed closed; a malformed
    one refuses the whole reading (correction 1)."""

    __slots__ = (
        "consumptions",
        "launches",
        "receipts",
        "records",
        "reservations",
        "resolutions",
        "statements",
        "store",
    )

    def __init__(self, store: Any, cells: Any) -> None:
        from kalpamani.data.production.sharadar import deletion_rehearsal as dr
        from kalpamani.data.production.sharadar import deletion_rehearsal_launch as dl
        from kalpamani.data.production.sharadar import deletion_rehearsal_task as dt

        records_dir: Path = store._records_dir
        self.store = store
        self.statements: list[Any] = []
        self.launches: list[Any] = []
        self.records: list[Any] = []
        self.receipts: list[Any] = []
        try:
            for path in sorted(records_dir.glob(f"{_STATEMENT_PREFIX}-*.json")):
                self.statements.append(dt.parse_rehearsal_statement(path.read_bytes()))
            for path in sorted(records_dir.glob(f"{_LAUNCH_PREFIX}-*.json")):
                self.launches.append(dl.parse_rehearsal_launch_record(path.read_bytes()))
            for path in sorted(records_dir.glob(f"{_RECORD_PREFIX}-*.json")):
                self.records.append(dr.parse_rehearsal_record(path.read_bytes()))
            for path in sorted(records_dir.glob(f"{_RECEIPT_PREFIX}-*.json")):
                self.receipts.append(dl.parse_rehearsal_receipt_evidence(path.read_bytes()))
            self.reservations: dict[str, Any] = dl.rehearsal_reservations(store)
            self.resolutions: dict[str, Any] = dl.rehearsal_resolutions(store)
            self.consumptions: dict[str, bytes] = store.consumptions(dr.REHEARSAL_CONSUMPTION_KIND)
        except Exception:
            raise cells.PermissionToolRefusalError(
                "refused_rehearsal_records", EXIT_REFUSED_REHEARSAL_RECORDS
            ) from None

    def unsettled(self, cleanups: Any) -> list[Any]:
        from kalpamani.data.production.sharadar import deletion_rehearsal_launch as dl

        return dl.unsettled_rehearsals(self.store, cleanups)

    def bind(self, record: Any, target: Any) -> Any:
        """The one evidence-binding rule over this evidence (raises RehearsalBindingError)."""
        from kalpamani.data.production.sharadar.deletion_rehearsal_launch import (
            bind_rehearsal_result,
        )

        return bind_rehearsal_result(
            record,
            target=target,
            consumptions=self.consumptions,
            reservations=self.reservations.values(),
            launches=self.launches,
            receipts=self.receipts,
        )

    def bind_with(self, record: Any, target: Any, receipt: Any) -> Any:
        """The rule with ``receipt`` standing in for a retained receipt of its launch when
        none is retained yet (the completion's own, before it is written)."""
        from kalpamani.data.production.sharadar.deletion_rehearsal_launch import (
            bind_rehearsal_result,
        )

        retained = [
            r for r in self.receipts if r.launch_record_sha256 == receipt.launch_record_sha256
        ]
        receipts = list(self.receipts) if retained else [*self.receipts, receipt]
        return bind_rehearsal_result(
            record,
            target=target,
            consumptions=self.consumptions,
            reservations=self.reservations.values(),
            launches=self.launches,
            receipts=receipts,
        )

    def bound_results(
        self, binding: Any, target: Any, evidence: Any, attempt: str | None
    ) -> list[Any]:
        """Every record under ``binding`` that binds to its evidence for exactly ``target``
        and reads PASSED with the control principal's cleanups -- the only records the
        sequence and the prerequisite admission count."""
        from kalpamani.data.production.sharadar.deletion_rehearsal import (
            RehearsalStatus,
            derive_rehearsal,
        )
        from kalpamani.data.production.sharadar.deletion_rehearsal_launch import (
            RehearsalBindingError,
        )

        found: list[Any] = []
        for record in self.records:
            if record.binding != binding or attempt is None:
                continue
            try:
                self.bind(record, target)
            except RehearsalBindingError:
                continue
            status, _ = derive_rehearsal(record, evidence.cleanups, prerequisite_attempt=attempt)
            if status is RehearsalStatus.PASSED:
                found.append(record)
        return found

    def earlier(
        self, binding: Any, target: Any, evidence: Any, attempt: str | None
    ) -> tuple[str, ...]:
        """The rehearsal subcells PASSED and bound for exactly this target: what
        :func:`prepare_rehearsal` needs to admit the next subcell of the sequence."""
        return tuple(
            sorted({r.subcell_id for r in self.bound_results(binding, target, evidence, attempt)})
        )

    def completion_state(self, launch: Any) -> tuple[Any, Any]:
        """What a launch's completion already wrote: its record (by statement, authorization
        and stamp) and its retained receipt (by launch-record digest), each exactly one or
        none; two of either refuse as conflicting evidence."""
        from kalpamani.data.production.sharadar.deletion_rehearsal_task import (
            REHEARSAL_IDENTITY_PREFIX,
        )

        stamp = launch.identity[len(REHEARSAL_IDENTITY_PREFIX) :]
        records = [
            r
            for r in self.records
            if r.statement_sha256 == launch.statement_sha256
            and r.authorization_sha256 == launch.authorization_sha256
            and r.stamp == stamp
        ]
        receipts = [r for r in self.receipts if r.launch_record_sha256 == launch.digest]
        if len(records) > 1 or len(receipts) > 1:
            raise ValueError("conflicting completion evidence")
        return (records[0] if records else None, receipts[0] if receipts else None)

    def pending_launch(self, subcell_id: str, binding: Any) -> Any:
        """The one LAUNCHED, terminal launch of ``subcell_id`` under ``binding`` whose
        completion is not whole (no record, or no retained receipt), or ``None``."""
        from kalpamani.data.production.sharadar.deletion_rehearsal_launch import (
            RehearsalLaunchOutcome,
        )

        pending = []
        for launch in self.launches:
            if (
                launch.subcell_id != subcell_id
                or launch.binding != binding
                or launch.outcome is not RehearsalLaunchOutcome.LAUNCHED
                or launch.observed_exit_code is None
            ):
                continue
            record, receipt = self.completion_state(launch)
            if record is None or receipt is None:
                pending.append(launch)
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
    try:
        rehearsal = _RehearsalEvidence(admitted.store, cells)
    except ValueError:
        raise cells.PermissionToolRefusalError(
            "refused_rehearsal_records", EXIT_REFUSED_REHEARSAL_RECORDS
        ) from None
    return admitted, evidence, rehearsal


def _current_target(evidence: Any, cells: Any) -> tuple[Any, str | None]:
    """The exact deletion target the R-4 record binds today, and its prerequisite attempt;
    ``(None, None)`` when no target is bound (nothing is earlier, nothing binds)."""
    from kalpamani.data.production.sharadar.deletion_rehearsal import (
        REHEARSAL_PREREQUISITE,
        RehearsalError,
        rehearsal_target,
    )

    try:
        target = rehearsal_target(evidence)
    except RehearsalError:
        return None, None
    for record in evidence.records.get(REHEARSAL_PREREQUISITE, ()):
        if (
            record.binding == evidence.binding
            and record.created_bucket == target.bucket
            and record.created_key == target.key
        ):
            return target, str(record.attempt_sha256)
    return target, None


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

    target, attempt = _current_target(evidence, cells)
    try:
        statement = prepare_rehearsal(
            subcell_id,
            evidence,
            stamp=stamp,
            earlier=rehearsal.earlier(binding, target, evidence, attempt),
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
    target, attempt = _current_target(evidence, cells)
    try:
        statement = prepare_rehearsal(
            subcell_id,
            evidence,
            stamp=r3.new_stamp(now()),
            earlier=rehearsal.earlier(admitted.binding, target, evidence, attempt),
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
    if rehearsal.unsettled(evidence.cleanups):
        # Correction 1: an unsettled reservation beside the ledger -- interrupted, or its
        # task not confirmed stopped -- blocks every launch before anything is consumed,
        # whatever the subcell, the records directory or the authorization.
        raise cells.PermissionToolRefusalError(
            "refused_rehearsal_recovery_pending", cells.EXIT_REFUSED_RECOVERY_PENDING
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
        cleanups=evidence.cleanups,
    )
    print(
        f"rehearsal launch={report.outcome.value} subcell={subcell_id} "
        f"run_tasks={report.run_tasks} describes={report.describes} stops={report.stops} "
        f"parameter_puts={report.parameter_puts} parameter_deletes={report.parameter_deletes} "
        f"task_state={'none' if report.task_state is None else report.task_state.value} "
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
    if report.outcome is RehearsalLaunchOutcome.REFUSED_RECOVERY_PENDING:
        raise cells.PermissionToolRefusalError(
            "refused_rehearsal_recovery_pending", cells.EXIT_REFUSED_RECOVERY_PENDING
        )
    if report.outcome is RehearsalLaunchOutcome.REFUSED_RESERVED:
        raise cells.PermissionToolRefusalError(
            "refused_rehearsal_reserved", cells.EXIT_REFUSED_RESERVATION
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
        launch,
        decode_receipt_line(line),
        admitted,
        evidence,
        rehearsal,
        now=now,
        cells=cells,
        parsed=parsed,
        hand_receipt=None,
    )


def recover(
    subcell_id: str,
    parsed: argparse.Namespace,
    *,
    env: Mapping[str, str],
    seams: dict[str, Any],
    cells: Any,
) -> int:
    """Record an interrupted rehearsal launch offline: exactly one reservation of the
    subcell beside the ledger with no resolution. Nothing is launched, nothing is
    retried, no client exists; whether a task started stays UNKNOWN until the cleanup
    lists the reservation's tag and confirms every discovered task stopped."""
    from kalpamani.data.production.sharadar.deletion_rehearsal_launch import (
        recover_rehearsal_launch,
    )
    from kalpamani.data.production.sharadar.launch_store import StoreError

    _subcell(subcell_id, cells)
    now: Callable[[], datetime] = seams["now"]
    admitted, evidence, rehearsal = _admitted(parsed, env, seams, cells)
    interrupted = [
        u.reservation
        for u in rehearsal.unsettled(evidence.cleanups)
        if u.needs_recovery and u.reservation.subcell_id == subcell_id
    ]
    if len(interrupted) != 1:
        raise cells.PermissionToolRefusalError(
            "refused_rehearsal_recovery", cells.EXIT_REFUSED_RECOVERY
        )
    reservation = interrupted[0]
    try:
        resolution = recover_rehearsal_launch(admitted.store, reservation, now=now())
    except StoreError:
        raise cells.PermissionToolRefusalError(
            "refused_record_write", cells.EXIT_REFUSED_RECORD_WRITE
        ) from None
    print(
        f"rehearsal recovery subcell={subcell_id} outcome={resolution.outcome} "
        f"task_state={resolution.task_state.value} started_by={reservation.started_by} "
        f"reservation_sha256={reservation.digest}"
    )
    print(SENTENCES["rehearsal_recovered"])
    return int(cells.EXIT_RECOVERED)


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
    launch = rehearsal.pending_launch(subcell_id, admitted.binding) or _whole_launch(
        rehearsal, subcell_id, admitted.binding
    )
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
    return _complete(
        launch,
        document,
        admitted,
        evidence,
        rehearsal,
        now=now,
        cells=cells,
        parsed=parsed,
        hand_receipt=lines[0],
    )


def _whole_launch(rehearsal: _RehearsalEvidence, subcell_id: str, binding: Any) -> Any:
    """The one already-whole launch of ``subcell_id`` (record and receipt both present), so
    a repeated completion can say so, or ``None``."""
    from kalpamani.data.production.sharadar.deletion_rehearsal_launch import (
        RehearsalLaunchOutcome,
    )

    whole = []
    for launch in rehearsal.launches:
        if (
            launch.subcell_id != subcell_id
            or launch.binding != binding
            or launch.outcome is not RehearsalLaunchOutcome.LAUNCHED
            or launch.observed_exit_code is None
        ):
            continue
        record, receipt = rehearsal.completion_state(launch)
        if record is not None and receipt is not None:
            whole.append(launch)
    return whole[-1] if whole else None


def _complete(
    launch: Any,
    document: dict[str, Any],
    admitted: Any,
    evidence: Any,
    rehearsal: _RehearsalEvidence,
    *,
    now: Callable[[], datetime],
    cells: Any,
    parsed: argparse.Namespace,
    hand_receipt: str | None,
) -> int:
    """The rehearsal record from the verified receipt, bound by the one rule, written with
    its retained receipt; then the reading with the control principal's cleanups.

    **Repeatable** (correction 1): an interruption between the record and the retained
    receipt is repaired by running the same completion again with the same receipt, which
    writes exactly what is missing; a completion that is already whole changes nothing and
    says so; another receipt refuses. **The collector's contradiction and disposition rules
    apply to the hand path too**: a hand-read receipt over a recorded, unresolved
    contradiction needs the owner's acknowledgement by digest and is then disposed, bound to
    this receipt beside the record; a disposition already binding the launch to another
    receipt refuses this one.
    """
    from kalpamani.data.production.sharadar.deletion_rehearsal import (
        RehearsalStatus,
        derive_rehearsal,
    )
    from kalpamani.data.production.sharadar.deletion_rehearsal_launch import (
        RehearsalBindingError,
        RehearsalCompletionError,
        RehearsalReceiptEvidence,
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
    dispositions: list[dict[str, Any]] = []
    if hand_receipt is not None:
        dispositions = cells._dispositions_for(
            parsed,
            records_dir=admitted.store._records_dir,
            identity=launch.identity,
            launch_record_sha256=launch.digest,
            receipt_text=hand_receipt,
            now=now,
        )
    existing_record, existing_receipt = rehearsal.completion_state(launch)
    receipt_evidence = RehearsalReceiptEvidence(
        identity=launch.identity,
        subcell_id=launch.subcell_id,
        statement_sha256=launch.statement_sha256,
        launch_record_sha256=launch.digest,
        receipt=dict(document),
        received_at=now(),
        binding=admitted.binding,
    )
    if existing_record is not None and existing_record.document() != record.document():
        # A record exists and this receipt establishes something else: not a repeat.
        raise cells.PermissionToolRefusalError("refused_completion", cells.EXIT_REFUSED_COMPLETION)
    if existing_receipt is not None and existing_receipt.receipt != document:
        raise cells.PermissionToolRefusalError("refused_completion", cells.EXIT_REFUSED_COMPLETION)
    write_record = existing_record is None
    write_receipt = existing_receipt is None
    if not (write_record or write_receipt or dispositions):
        raise cells.PermissionToolRefusalError(
            "rehearsal_completion_recorded", cells.EXIT_COMPLETION_RECORDED
        )
    # The one evidence-binding rule, before anything is written: the consumption, the
    # reservation, the launch's binding to it, the receipt (the retained one, or the one
    # about to be retained) and the record must form one chain for exactly this target.
    try:
        rehearsal.bind_with(record, statement.target, receipt_evidence)
    except RehearsalBindingError as error:
        print(f"rehearsal evidence does not bind: {error.defect.value}")
        raise cells.PermissionToolRefusalError(
            "refused_completion", cells.EXIT_REFUSED_COMPLETION
        ) from None
    try:
        for disposition in dispositions:
            admitted.store.write_record("collection-disposition", disposition, at=now())
        if write_record:
            admitted.store.write_record(_RECORD_PREFIX, record.document(), at=now())
        if write_receipt:
            admitted.store.write_record(
                _RECEIPT_PREFIX, receipt_evidence.document(), at=receipt_evidence.received_at
            )
    except Exception:
        raise cells.PermissionToolRefusalError(
            "refused_record_write", cells.EXIT_REFUSED_RECORD_WRITE
        ) from None
    _target, prerequisite_attempt = _current_target(evidence, cells)
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


def rehearsal_tasks_to_settle(store: Any, cleanups: Any) -> list[Any]:
    """What the control principal's cleanup settles for the rehearsal: every unsettled
    reservation beside the ledger whose task state is not self-settled -- discovered on the
    reservation's cluster by the reservation's tag, its known task (when one was recorded)
    confirmed by exact identity. Keyed by the reservation's digest; a malformed reservation
    or resolution refuses rather than hides."""
    from kalpamani.data.production.sharadar import deletion_rehearsal_launch as dl
    from kalpamani.data.production.sharadar import permission_cells as pc

    found = []
    for unsettled in dl.unsettled_rehearsals(store, cleanups):
        reservation = unsettled.reservation
        resolution = unsettled.resolution
        known: tuple[str, ...] = ()
        if resolution is not None and resolution.task_id is not None:
            known = (resolution.task_id,)
        found.append(
            pc.TasksToSettle(
                attempt_sha256=reservation.digest,
                started_by=reservation.started_by,
                cluster_arn=reservation.cluster_arn,
                known_task_ids=known,
            )
        )
    return found


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
        parsed.recover_rehearsal_launch is not None,
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
    if parsed.acknowledged_contradictions and (
        parsed.complete_rehearsal is None
        or parsed.receipt_lines is None
        or any(
            not isinstance(d, str) or cells._SHA256_RE.fullmatch(d) is None
            for d in parsed.acknowledged_contradictions
        )
    ):
        # An acknowledgement belongs to a hand-read completion only, and names a digest.
        return False
    if parsed.ledger is None or parsed.launch_inputs is None or parsed.records_dir is None:
        return False
    if parsed.recover_rehearsal_launch is not None:
        return not (
            parsed.authorized
            or parsed.collection_authorized
            or parsed.authorization is not None
            or parsed.receipt_lines is not None
            or parsed.rehearsal_inputs is not None
        )
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
        if parsed.recover_rehearsal_launch is not None:
            return recover(
                parsed.recover_rehearsal_launch, parsed, env=env, seams=seams, cells=cells
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
    "recover",
    "rehearsal_tasks_to_settle",
    "rehearse",
    "run",
]
