"""The verification cell runner (readiness S9; ADR-0036 §3; proposed ADR-0046). Refuses by default.

Orchestrates the cells the accepted contracts require by composing the accepted tools
and adding nothing to their contracts: the launch tool (one prepared specification, one
identity, one authorization, one launch), its ledger-anchored reservation store, the
receipt validator behind ``--complete-row``, and the isolation-verdict path behind
``--isolation-verdict``. The R-3 cell's evidence is the R-3 tool's record; the negative
R-1 cells and the R-4 … R-9 permission cells are enumerated with their exact
requirements and stay ``BLOCKED`` or ``UNEXECUTED`` (:mod:`verification_cells`).

```text
matrix        (default) derive every cell's status from the recorded state -- the ledger,
              the reservations beside it, the verdict records, the R-3 record and the
              launch-inputs record -- and print the completion matrix; no client, nothing
              launched, nothing written
prepare       --prepare-cell <id> --identity verify-…: the launch tool's offline preparation
              for this cell (specification written, digest printed); the cell's identity and
              digest recorded beside the ledger under the ledger lock; no client
execute       --execute-cell <id> + the flag + --authorization: the cell must be PREPARED,
              every prerequisite PASSED, the authorization must name the prepared digest;
              then exactly the launch tool's authorized branch for that one identity --
              never a second launch of the same cell, never a retry of an uncertain one
complete      --complete-cell <id> --launch-record --receipt-lines: the launch tool's
              --complete-row for the cell's record
verdict       --verdict-cell R2-BLD-ISOLATION --launch-record --receipt-lines
              [--reachability-evidence]: the launch tool's --isolation-verdict; allowed while
              the cell is UNEXECUTED or INCONCLUSIVE, so a later transcription for the SAME
              launch can resolve an earlier insufficiency (no relaunch, no new probe, every
              record kept; a FAILED or contradictory record is never resolved away)
reconcile     the matrix mode IS the reconciliation: an identity reserved but unrecorded is
              INTERRUPTED and the only route is the launch tool's --recover; a consumed
              identity is never relaunched
```

**One identity, one authorization, one cell.** Preparation records the cell's identity
and specification digest; execution refuses unless the authorization names exactly that
digest and the cell is exactly ``PREPARED``; the launch tool then performs its own
binding, reservation and freshness checks. No authorization is generated here and none
is reused across cells. **A failed prerequisite blocks its dependants** (R-3 gates every
runtime cell; the build isolation verdict needs the build bootstrap cell PASSED).
**Bootstrap completion and R-2 isolation are separate cells**, and a non-connection
without qualifying corroboration stays ``INCONCLUSIVE``. Receipt collection stays
deferred: the owner supplies the receipt lines and the transcription.

**It has never run against AWS.** Every client it could build is the launch tool's, and
every test injects fakes for all of them.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import secrets
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

REPO_ROOT: Final = Path(__file__).resolve().parents[1]
for _entry in (REPO_ROOT / "src", REPO_ROOT / "scripts"):
    if str(_entry) not in sys.path:  # pragma: no cover - import bootstrap
        sys.path.insert(0, str(_entry))

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex  # noqa: E402
from kalpamani.data.production.sharadar import verification_cells as vc  # noqa: E402
from kalpamani.data.production.sharadar.release import ReleaseMode  # noqa: E402

AUTHORIZATION_FLAG: Final = "--i-am-the-owner-authorizing-one-cell-launch"
CELLS_SUFFIX: Final = ".cells.json"

REFUSED_FLAGS: Final[dict[str, str]] = {
    "--all": "cells are prepared and executed one at a time, each under its own authorization",
    "--run-all": "same as --all",
    "--retry": "an uncertain launch is never retried; recover it",
    "--force": "nothing here can be forced",
    "--skip-prerequisites": "a failed prerequisite blocks its dependants",
    "--bypass": "there is no bypass",
    "--relaunch": "a consumed identity is never launched again",
    "--auto-authorize": "no authorization is generated here",
}

EXIT_MATRIX: Final = 0
EXIT_PREPARED: Final = 0
EXIT_COMPLETED: Final = 0
EXIT_REFUSED_ARGUMENTS: Final = 2
EXIT_REFUSED_RECORDS: Final = 3
EXIT_REFUSED_CELL_STATE: Final = 4
EXIT_REFUSED_PREREQUISITE: Final = 5
EXIT_REFUSED_AUTHORIZATION: Final = 6
EXIT_REFUSED_LEDGER_LOCKED: Final = 13

SENTENCES: Final[dict[str, str]] = {
    "refused_arguments": "cells refused: the arguments were not admitted",
    "refused_records": "cells refused: an owner record was not admitted",
    "refused_cell_state": "cells refused: the cell is not in the state this mode needs",
    "refused_prerequisite": "cells refused: a prerequisite cell has not passed",
    "refused_authorization": (
        "cells refused: the authorization does not name the prepared specification"
    ),
    "refused_ledger_locked": "cells refused: the ledger is locked by another process",
    "prepared": "cell prepared offline; authorize its specification digest to execute it",
    "matrix": "completion matrix derived from recorded state; nothing was launched",
}


class CellsRefusalError(Exception):
    """A closed refusal: one sentence key and one exit code."""

    def __init__(self, key: str, exit_code: int) -> None:
        super().__init__(key)
        self.key = key
        self.exit_code = exit_code


def _launch_tool() -> Any:
    """The accepted launch tool, loaded from ``scripts/`` as a module."""
    name = "production_launch"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, REPO_ROOT / "scripts" / "production_launch.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _r3_tool() -> Any:
    name = "production_r3_verification"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, REPO_ROOT / "scripts" / "production_r3_verification.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _permission_tool() -> Any:
    name = "production_permission_cells"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, REPO_ROOT / "scripts" / "production_permission_cells.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="production_verification_cells",
        description="the verification cell runner; derives the matrix by default, launches nothing",
    )
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--launch-inputs", required=True, type=Path)
    parser.add_argument("--records-dir", required=True, type=Path)
    parser.add_argument("--r3-record", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare-cell")
    mode.add_argument("--execute-cell")
    mode.add_argument("--complete-cell")
    mode.add_argument("--verdict-cell")
    parser.add_argument("--identity")
    parser.add_argument("--slice", dest="slice_path", type=Path)
    parser.add_argument("--run-identity", dest="run_identities", action="append", default=[])
    parser.add_argument("--production-configuration", type=Path)
    parser.add_argument("--verification-configuration", type=Path)
    parser.add_argument("--acquisition-configuration", type=Path)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--launch-record", type=Path)
    parser.add_argument("--receipt-lines", type=Path)
    parser.add_argument("--reachability-evidence", type=Path)
    parser.add_argument(AUTHORIZATION_FLAG, dest="authorized", action="store_true")
    return parser


# ---------------------------------------------------------------------------
# Recorded state
# ---------------------------------------------------------------------------


def cells_path(store: Any) -> Path:
    """The prepared-cells document, beside the canonical ledger."""
    ledger: Path = store.ledger_path
    return ledger.with_name(ledger.name + CELLS_SUFFIX)


def read_prepared(store: Any) -> dict[str, vc.PreparedCell]:
    path = cells_path(store)
    if not path.exists():
        return {}
    try:
        return vc.parse_cells_document(path.read_bytes())
    except (OSError, vc.CellsDocumentError):
        raise CellsRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None


def write_prepared(store: Any, prepared: dict[str, vc.PreparedCell]) -> None:
    """Replace the prepared-cells document atomically (temporary file, fsync, os.replace)."""
    path = cells_path(store)
    payload = canonical_bytes(vc.cells_document(prepared.values()))
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    descriptor = os.open(
        str(temporary), os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    )
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.replace(temporary, path)
    except OSError:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise CellsRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None


def _closed_records(
    store: Any, prefix: str, parse: Callable[[Any], Any]
) -> tuple[dict[str, tuple[Any, ...]], frozenset[str], int]:
    """Every ``<prefix>-*.json`` record in the records directory, parsed closed.

    Returns the parsed documents grouped by the specification digest they name, the
    digests named by files that decode but do not parse closed (malformed evidence for a
    launch is reported against that launch, never ignored), and the count of files that
    could not be decoded at all. Nothing is ranked here: the cell matrix resolves the
    documents deterministically.
    """
    from kalpamani.data.production.sharadar.documents import decode_document
    from kalpamani.data.production.sharadar.launch_records import MAX_RECORD_BYTES

    parsed: dict[str, list[Any]] = {}
    malformed: set[str] = set()
    unreadable = 0
    records_dir: Path = store._records_dir
    if not records_dir.is_dir():
        return {}, frozenset(), 0
    for path in sorted(records_dir.glob(f"{prefix}-*.json")):
        try:
            raw = path.read_bytes()
            document = decode_document(raw, max_bytes=MAX_RECORD_BYTES)
        except Exception:
            unreadable += 1
            continue
        try:
            record = parse(document)
        except ValueError:
            digest = document.get("specification_digest") if type(document) is dict else None
            if type(digest) is str and digest:
                malformed.add(digest)
            else:
                unreadable += 1
            continue
        parsed.setdefault(record.specification_digest, []).append(record)
    return (
        {
            digest: tuple(sorted(docs, key=lambda d: d.recorded_at))
            for digest, docs in parsed.items()
        },
        frozenset(malformed),
        unreadable,
    )


def _verdicts(store: Any) -> tuple[dict[str, tuple[Any, ...]], frozenset[str], int]:
    """Every verdict record, parsed closed (:func:`_closed_records`)."""
    from kalpamani.data.production.sharadar.probe import parse_isolation_verdict_document

    return _closed_records(store, "isolation-verdict", parse_isolation_verdict_document)


def _negative_evidence(store: Any) -> tuple[dict[str, tuple[Any, ...]], frozenset[str], int]:
    """Every negative launch evidence record, parsed closed (:func:`_closed_records`)."""
    return _closed_records(store, "negative-launch-evidence", vc.parse_negative_launch_evidence)


def permission_evidence(store: Any, binding: Any) -> Any:
    """Every permission record, attempt and cleanup in the records directory, parsed closed.

    Grouped by subcell (records, attempts) or kept in order (cleanups); a file that does
    not parse is counted as malformed, which makes every permission subcell UNBOUND until
    it is removed or repaired -- malformed evidence is reported, never ignored.
    """
    from kalpamani.data.production.sharadar import permission_cells as pc
    from kalpamani.data.production.sharadar.documents import decode_document
    from kalpamani.data.production.sharadar.launch_records import MAX_RECORD_BYTES

    records: dict[str, list[Any]] = {}
    attempts: dict[str, list[Any]] = {}
    cleanups: list[Any] = []
    malformed = 0
    records_dir: Path = store._records_dir
    if not records_dir.is_dir():
        return pc.PermissionEvidence(binding=binding)
    parsers: tuple[tuple[str, Callable[[Any], Any], dict[str, list[Any]] | None], ...] = (
        ("permission-record", pc.parse_permission_record, records),
        ("permission-attempt", pc.parse_permission_attempt, attempts),
        ("permission-cleanup", pc.parse_permission_cleanup, None),
    )
    for prefix, parse, sink in parsers:
        for path in sorted(records_dir.glob(f"{prefix}-*.json")):
            try:
                parsed = parse(decode_document(path.read_bytes(), max_bytes=MAX_RECORD_BYTES))
            except Exception:
                malformed += 1
                continue
            if sink is None:
                cleanups.append(parsed)
            else:
                sink.setdefault(parsed.subcell_id, []).append(parsed)
    return pc.PermissionEvidence(
        records={k: tuple(sorted(v, key=lambda r: r.started_at)) for k, v in records.items()},
        attempts={k: tuple(sorted(v, key=lambda a: a.started_at)) for k, v in attempts.items()},
        cleanups=tuple(sorted(cleanups, key=lambda c: c.recorded_at)),
        malformed=malformed,
        binding=binding,
    )


def recorded_evidence(
    arguments: argparse.Namespace,
    store: Any,
    *,
    r3_binding_source: Callable[[], Any] | None,
) -> vc.RecordedEvidence:
    """Everything the matrix is derived from, read once."""
    from kalpamani.data.production.sharadar import launch_records as lr
    from kalpamani.data.production.sharadar.launch_store import StoreError
    from kalpamani.data.production.sharadar.r3_verification import R3RecordError, parse_r3_record

    try:
        ledger, _ = store.read_ledger()
        unreconciled = frozenset(store.unreconciled(ledger))
    except StoreError:
        raise CellsRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
    prepared = read_prepared(store)
    reservations: dict[str, Any] = {}
    for cell in prepared.values():
        try:
            reservation = store.reservation(cell.identity)
        except StoreError:
            raise CellsRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
        if reservation is not None:
            reservations[cell.identity] = reservation
    launch_records: dict[str, Any] = {}
    duplicated: set[str] = set()
    unreadable_launch_records = 0
    for path in store.launch_records():
        try:
            record = lr.parse_launch_record(path.read_bytes())
        except (OSError, lr.LaunchRecordError):
            unreadable_launch_records += 1
            continue
        if record.identity in launch_records or record.identity in duplicated:
            # Two records for one identity: neither can be the launch, so neither binds.
            unreadable_launch_records += 1
            duplicated.add(record.identity)
            launch_records.pop(record.identity, None)
            continue
        launch_records[record.identity] = record
    verdicts, malformed_verdicts, unreadable_verdicts = _verdicts(store)
    negative, malformed_negative, unreadable_negative = _negative_evidence(store)
    inputs = None
    try:
        inputs = lr.parse_launch_inputs(arguments.launch_inputs.read_bytes())
    except (OSError, lr.LaunchRecordError):
        raise CellsRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
    r3_record = None
    r3_binding = None
    if arguments.r3_record is not None:
        try:
            r3_record = parse_r3_record(arguments.r3_record.read_bytes())
        except (OSError, R3RecordError):
            raise CellsRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
        if r3_binding_source is not None:
            try:
                r3_binding = r3_binding_source()
            except Exception:
                r3_binding = None
    # The permission binding: the same environment binding, the production declarations
    # and the registration the targets were resolved from. Absent when the R-3 binding
    # is (nothing to hold the evidence to).
    permission_binding = None
    if r3_binding is not None:
        from kalpamani.data.production.sharadar import permission_cells as pc

        try:
            permission_binding = pc.PermissionBinding(
                environment_binding_sha256=r3_binding.environment_binding_sha256,
                policy_declaration_sha256=pc.declaration_digest(
                    _permission_tool().declaration_paths()
                ),
                registration_sha256=sha256_hex(arguments.launch_inputs.read_bytes()),
                partition=r3_binding.partition,
                region=r3_binding.region,
            )
        except (OSError, ValueError):
            permission_binding = None
    permission = permission_evidence(store, permission_binding)
    return vc.RecordedEvidence(
        ledger=ledger,
        unreconciled=unreconciled,
        verdicts=verdicts,
        malformed_verdicts=malformed_verdicts,
        unreadable_verdicts=unreadable_verdicts,
        reservations=reservations,
        launch_records=launch_records,
        unreadable_launch_records=unreadable_launch_records,
        inputs=inputs,
        r3_record=r3_record,
        r3_binding=r3_binding,
        negative_evidence=negative,
        malformed_negative_evidence=malformed_negative,
        unreadable_negative_evidence=unreadable_negative,
        permission=permission,
    )


def _current_r3_binding() -> Any:
    """The binding an R-3 record must carry today: the environment binding and storage.tf."""
    from kalpamani.data.qualify.sharadar.runtime_binding import (
        ENVIRONMENT_BINDING_ENV_VAR,
        load_environment_binding,
    )

    tool = _r3_tool()
    from aws_foundation_verify import expected_account

    environment = load_environment_binding(
        path=os.environ.get(ENVIRONMENT_BINDING_ENV_VAR, ""), expected_account=expected_account()
    )
    return tool.current_binding(environment)


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


def _launch_argv(
    arguments: argparse.Namespace,
    cell: vc.CellDefinition,
    identity: str,
    *,
    with_release_mode: bool = True,
) -> list[str]:
    assert cell.actor is not None
    argv = [
        "--actor",
        cell.actor.value,
        "--kind",
        "verification",
        "--identity",
        identity,
        "--ledger",
        str(arguments.ledger),
        "--launch-inputs",
        str(arguments.launch_inputs),
        "--records-dir",
        str(arguments.records_dir),
    ]
    if arguments.authorization is not None:
        argv += ["--authorization", str(arguments.authorization)]
    if arguments.slice_path is not None:
        argv += ["--slice", str(arguments.slice_path)]
    for run_identity in arguments.run_identities:
        argv += ["--run-identity", run_identity]
    for flag, value in (
        ("--production-configuration", arguments.production_configuration),
        ("--verification-configuration", arguments.verification_configuration),
        ("--acquisition-configuration", arguments.acquisition_configuration),
    ):
        if value is not None:
            argv += [flag, str(value)]
    # A negative cell's release mode is the cell definition's, bound into the prepared
    # specification (and so into the authorization's digest) -- never an owner argument.
    if (
        with_release_mode
        and cell.release_mode is not None
        and cell.release_mode is not ReleaseMode.NORMAL
    ):
        argv += ["--release-mode", cell.release_mode.value.lower()]
    return argv


#: The cells the launch tool executes: the positive bootstrap cells and the negative ones.
_LAUNCH_KINDS: Final[set[vc.CellKind]] = {vc.CellKind.RUNTIME_LAUNCH, vc.CellKind.NEGATIVE_LAUNCH}


def _cell(cell_id: str | None, kinds: set[vc.CellKind]) -> vc.CellDefinition:
    try:
        cell = vc.definition(cell_id or "")
    except ValueError:
        raise CellsRefusalError("refused_arguments", EXIT_REFUSED_ARGUMENTS) from None
    if cell.kind not in kinds:
        raise CellsRefusalError("refused_arguments", EXIT_REFUSED_ARGUMENTS)
    return cell


def prepare_cell(
    arguments: argparse.Namespace, launch: Any, store: Any, *, now: datetime, root_source: Any
) -> vc.PreparedCell:
    """The launch tool's offline preparation for one runtime cell, recorded beside the ledger."""
    cell = _cell(arguments.prepare_cell, _LAUNCH_KINDS)
    identity = arguments.identity
    if identity is None or not identity.startswith("verify-"):
        raise CellsRefusalError("refused_arguments", EXIT_REFUSED_ARGUMENTS)
    launch_arguments = launch.parse_arguments(_launch_argv(arguments, cell, identity))
    prepared = launch.prepare_launch(launch_arguments, now=now, root_source=root_source)
    launch.write_specification(launch_arguments, prepared, now=now)
    record = vc.PreparedCell(
        cell_id=cell.cell_id,
        identity=identity,
        specification_digest=prepared.specification.digest,
        prepared_at=now,
    )
    from kalpamani.data.production.sharadar.launch_store import StoreDefect, StoreError

    try:
        with store.locked(now=lambda: now):
            existing = read_prepared(store)
            # Another cell already holds this identity: one identity, one cell.
            for other_id, other in existing.items():
                if other.identity == identity and other_id != cell.cell_id:
                    raise CellsRefusalError("refused_cell_state", EXIT_REFUSED_CELL_STATE)
            existing[cell.cell_id] = record
            write_prepared(store, existing)
    except StoreError as error:
        if error.defect is StoreDefect.LEDGER_LOCKED:
            raise CellsRefusalError("refused_ledger_locked", EXIT_REFUSED_LEDGER_LOCKED) from None
        raise CellsRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
    return record


def _record_negative_evidence(
    launch: Any,
    store: Any,
    cell: vc.CellDefinition,
    prepared: vc.PreparedCell,
    mode_argv: list[str],
    *,
    now: datetime,
    root_source: Any,
) -> None:
    """Write the negative launch evidence record for a completed negative cell.

    The receipt is read again through the launch tool's own record-and-receipt reader
    (the same verification ``--complete-row`` performed), so the outcome recorded is
    the one bound to the launch record; the record is written under an exclusive name.
    A failure here leaves the ledger row as completed and the cell reads UNBOUND until
    the evidence is recorded, never PASSED.
    """
    from kalpamani.data.production.sharadar.launch_store import StoreError

    assert cell.release_mode is not None
    try:
        _store, record, verified = launch._record_and_receipt(
            launch.parse_arguments(mode_argv), root_source=root_source
        )
        document = vc.negative_evidence_document(
            cell=cell,
            identity=prepared.identity,
            specification_digest=record.specification_digest,
            release_mode=record.release_mode,
            receipt=verified,
            recorded_at=now,
        )
        store.write_record("negative-launch-evidence", document, at=now)
    except (launch.LaunchRefusalError, StoreError, ValueError, TypeError):
        raise CellsRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None


def _require_state(
    states: dict[str, vc.CellState],
    cell: vc.CellDefinition,
    allowed: set[vc.CellStatus],
    *,
    prerequisites: bool = True,
) -> None:
    """The cell must be in one of ``allowed``; with ``prerequisites``, its dependants passed.

    Recording evidence for a launch that already happened (completion) needs no
    prerequisite -- the launch did -- so completion checks the cell's own state only.
    """
    state = states[cell.cell_id]
    if state.status is vc.CellStatus.BLOCKED:
        raise CellsRefusalError("refused_prerequisite", EXIT_REFUSED_PREREQUISITE)
    if state.status not in allowed:
        raise CellsRefusalError("refused_cell_state", EXIT_REFUSED_CELL_STATE)
    if prerequisites:
        for dependency in cell.depends_on:
            if states[dependency].status is not vc.CellStatus.PASSED:
                raise CellsRefusalError("refused_prerequisite", EXIT_REFUSED_PREREQUISITE)


def main(
    argv: Sequence[str] | None = None,
    *,
    clients: Any = None,
    environment: Callable[[str], str | None] | None = None,
    now: Callable[[], datetime] | None = None,
    monotonic: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
    root_source: Callable[[], Path] | None = None,
    security_of: Callable[[Path], Any] | None = None,
    r3_binding_source: Callable[[], Any] | None = None,
) -> int:
    """Derive the matrix (default), or prepare / execute / complete / verdict one cell.

    Every keyword is a seam the launch tool takes, forwarded unchanged; with none
    injected, the launch tool builds its real clients only inside its own authorized
    branch, which this runner reaches only from ``--execute-cell`` with the flag.
    """
    arguments_list = list(sys.argv[1:] if argv is None else argv)
    for token in arguments_list:
        if token.split("=", 1)[0] in REFUSED_FLAGS:
            print(SENTENCES["refused_arguments"])
            return EXIT_REFUSED_ARGUMENTS
    try:
        arguments = _parser().parse_args(arguments_list)
    except SystemExit:
        print(SENTENCES["refused_arguments"])
        return EXIT_REFUSED_ARGUMENTS
    if arguments.authorized and arguments.execute_cell is None:
        print(SENTENCES["refused_arguments"])
        return EXIT_REFUSED_ARGUMENTS
    launch = _launch_tool()
    clock = now if now is not None else (lambda: datetime.now(tz=UTC))
    seams: dict[str, Any] = {
        "clients": clients,
        "environment": environment,
        "now": now,
        "monotonic": monotonic,
        "sleep": sleep,
        "root_source": root_source,
        "security_of": security_of,
    }
    binding_source = _current_r3_binding if r3_binding_source is None else r3_binding_source
    try:
        # Containment and the ledger-anchored store are the launch tool's own.
        probe_arguments = launch.LaunchArguments(
            actor="acquisition",
            kind="verification",
            identity="verify-probe",
            ledger=arguments.ledger,
            launch_inputs=arguments.launch_inputs,
            records_dir=arguments.records_dir,
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
            store = launch._store(probe_arguments, launch._private_root(root_source))
        except launch.LaunchRefusalError as refusal:
            print(launch.SENTENCES[refusal.key])
            return int(refusal.exit_code)
        if arguments.prepare_cell is not None:
            record = prepare_cell(arguments, launch, store, now=clock(), root_source=root_source)
            print(f"cell={record.cell_id} specification_digest={record.specification_digest}")
            print(SENTENCES["prepared"])
            return EXIT_PREPARED
        evidence = recorded_evidence(arguments, store, r3_binding_source=binding_source)
        prepared = read_prepared(store)
        states = vc.derive_states(evidence, prepared)
        if arguments.execute_cell is not None:
            cell = _cell(arguments.execute_cell, _LAUNCH_KINDS)
            if not arguments.authorized or arguments.authorization is None:
                raise CellsRefusalError("refused_arguments", EXIT_REFUSED_ARGUMENTS)
            _require_state(states, cell, {vc.CellStatus.PREPARED})
            record = prepared[cell.cell_id]
            # The authorization must name this cell's prepared specification, before the
            # launch tool's own check: an authorization for another cell is refused here.
            from kalpamani.data.production.sharadar.documents import decode_document
            from kalpamani.data.production.sharadar.launch_records import MAX_RECORD_BYTES

            try:
                document = decode_document(
                    arguments.authorization.read_bytes(), max_bytes=MAX_RECORD_BYTES
                )
            except Exception:
                raise CellsRefusalError(
                    "refused_authorization", EXIT_REFUSED_AUTHORIZATION
                ) from None
            if (
                type(document) is not dict
                or document.get("specification_digest") != record.specification_digest
                or document.get("identity") != record.identity
            ):
                raise CellsRefusalError("refused_authorization", EXIT_REFUSED_AUTHORIZATION)
            code: int = launch.main(
                [*_launch_argv(arguments, cell, record.identity), launch.AUTHORIZATION_FLAG],
                **seams,
            )
            evidence = recorded_evidence(arguments, store, r3_binding_source=binding_source)
            states = vc.derive_states(evidence, prepared)
            for line in vc.matrix_lines(states):
                print(line)
            return code
        if arguments.complete_cell is not None or arguments.verdict_cell is not None:
            completing = arguments.complete_cell is not None
            cell = _cell(
                arguments.complete_cell if completing else arguments.verdict_cell,
                _LAUNCH_KINDS if completing else {vc.CellKind.ISOLATION_VERDICT},
            )
            if arguments.launch_record is None or arguments.receipt_lines is None:
                raise CellsRefusalError("refused_arguments", EXIT_REFUSED_ARGUMENTS)
            launch_cell = cell if completing else vc.definition(cell.depends_on[0])
            if completing:
                _require_state(states, cell, {vc.CellStatus.LAUNCHED}, prerequisites=False)
            else:
                # An INCONCLUSIVE cell may be re-evaluated when qualifying evidence for the
                # SAME launch arrives: no new task, no new probe, every record kept; the
                # matrix resolves the records deterministically afterwards.
                _require_state(states, cell, {vc.CellStatus.UNEXECUTED, vc.CellStatus.INCONCLUSIVE})
            record = prepared[launch_cell.cell_id]
            mode_argv = _launch_argv(
                arguments, launch_cell, record.identity, with_release_mode=False
            )
            mode_argv = [
                a for a in mode_argv if a != "--authorization" and a != str(arguments.authorization)
            ]
            mode_argv += [
                "--complete-row" if completing else "--isolation-verdict",
                "--launch-record",
                str(arguments.launch_record),
                "--receipt-lines",
                str(arguments.receipt_lines),
            ]
            if not completing:
                if arguments.verification_configuration is None:
                    raise CellsRefusalError("refused_arguments", EXIT_REFUSED_ARGUMENTS)
                if arguments.reachability_evidence is not None:
                    mode_argv += ["--reachability-evidence", str(arguments.reachability_evidence)]
            code = launch.main(mode_argv, **seams)
            if (
                completing
                and cell.kind is vc.CellKind.NEGATIVE_LAUNCH
                and code == launch.EXIT_ROW_COMPLETED
            ):
                # The row now reads REFUSED and no more. Record which refusal the verified
                # receipt established -- re-verified against the launch record by the launch
                # tool's own reader -- so the matrix can hold the cell to the expected one.
                _record_negative_evidence(
                    launch, store, cell, record, mode_argv, now=clock(), root_source=root_source
                )
            evidence = recorded_evidence(arguments, store, r3_binding_source=binding_source)
            states = vc.derive_states(evidence, prepared)
            for line in vc.matrix_lines(states):
                print(line)
            return code
        for line in vc.matrix_lines(states):
            print(line)
        print(SENTENCES["matrix"])
        return EXIT_MATRIX
    except CellsRefusalError as refusal:
        print(SENTENCES[refusal.key])
        return refusal.exit_code
    except launch.LaunchRefusalError as refusal:
        print(launch.SENTENCES[refusal.key])
        return int(refusal.exit_code)


__all__ = [
    "AUTHORIZATION_FLAG",
    "CELLS_SUFFIX",
    "REFUSED_FLAGS",
    "SENTENCES",
    "CellsRefusalError",
    "cells_path",
    "main",
    "permission_evidence",
    "prepare_cell",
    "read_prepared",
    "recorded_evidence",
    "write_prepared",
]


if __name__ == "__main__":  # pragma: no cover - the owner's console entry
    sys.exit(main())
