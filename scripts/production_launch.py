"""The owner-side launch tool (ADR-0036 §2.12; proposed ADR-0045). **Refuses by default.**

One authorized launch of one identity of one kind -- production or verification -- for one
actor, composing the accepted libraries and adding nothing to their contracts:

```text
records      the owner ledger, the launch-inputs record (Terraform outputs, image-gate values
             and the transcribed task-definition evidence), the owner's written authorization
             record, the slice (acquisition) or the run identities (build) -- each parsed
             closed by kalpamani.data.production.sharadar.launch_records
prepare      (no flag) the canonical LAUNCH SPECIFICATION is built from the admitted records,
             written beside the ledger for review, and its digest printed -- the value the
             owner's authorization must name; no client, no reservation, nothing launched
launch       (flag + authorization naming this specification) the identity is RESERVED durably
             and exclusively BEFORE any bootstrap or client -- beside the ledger, carrying the
             specification; then human_bootstrap under the human and launcher profiles,
             launch_authorized_run on real clients built only here, a launch record (naming
             the specification digest and the verified placement) and a sanitized evidence
             document under names that cannot collide, and one EXIT_CODE_ONLY ledger row
             written atomically under the ledger lock
completion   --complete-row: the receipt line the owner read from the log stream, verified
             against the launch record (itself bound to its reservation), completes the row --
             under the same lock and replacement
recovery     --recover: an identity reserved but never recorded (an interruption) receives its
             ledger row from the reservation's own specification and is never launched again;
             nothing is launched; the reservation is found beside the ledger whatever records
             directory is named
verdict      --isolation-verdict: the R-2 verdict from the verified receipt, the launch record,
             the reservation's specification and the owner's transcribed Reachability Analyzer
             evidence, derived and recorded; the placement is the recorded one, never a
             freshly supplied file's
```

**The records directory is an evidence destination.** Reservations and the ledger lock hang
off the ledger's canonical path (``<ledger>.reservations/``, ``<ledger>.lock``), so naming a
different ``--records-dir`` -- or the same one spelled differently -- changes where evidence
lands and nothing about which identities are consumed or await recovery. A ``reservations``
directory left under the supplied records directory by the first revision refuses until the
owner has moved its files beside the ledger by hand; the tool moves, reads and deletes none
of them.

**What the tool never does.** It never retries a ``RunTask`` (the adapter issues exactly
one; an ambiguous outcome is recorded as such and the identity stays consumed); it never
launches an identity the ledger or the ledger's reservations already hold, for either
kind; it never lets a verification launch spend a production identity (the ``verify-``
prefix is reserved and checked on every record); it never reads a receipt for the task
(the owner hands it the line); it never prints an ARN, an account id, a bucket, a key or
an identity; it never removes a reservation or another process's lock.

**The trust boundary is the owner's private root.** The digests that bind the
specification, the reservation, the launch record, the ledger row and the receipt to one
launch make a substituted or mislaid artifact a refusal; they are not protection against an
owner who deliberately rewrites every owner-controlled artifact consistently, and nothing
here claims otherwise.

**An ordinary import does nothing observable**, and so does an invocation without the
authorization flag. Every SDK import sits inside the authorized branch. **This tool has
never run against AWS**: every test injects fakes.

Refused by name, so a wrong reflex fails loudly: ``--run``, ``--live``, ``--execute``,
``--force``, ``--retry``, ``--profile``, ``--aws-profile``, ``--skip-placement``,
``--no-cleanup``, ``--task-arn``, ``--release-reservation``.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Protocol

#: The one flag that opens the authorized branch. Long on purpose.
AUTHORIZATION_FLAG: Final = "--i-am-the-owner-authorizing-one-launch"
#: The flag that admits one bounded receipt collection (ADR-0049 s.2): a logs read
#: under the actor's launcher profile, after that identity is proven, for one launch record.
COLLECT_FLAG: Final = "--i-am-the-owner-authorizing-receipt-collection"

#: Spellings a reflex might reach for. Each is refused with a reason before parsing.
REFUSED_FLAGS: Final[dict[str, str]] = {
    "--run": "there is no run switch; the authorization flag and record are the only route",
    "--live": "there is no live switch; every launch is the one the authorization names",
    "--execute": "there is no execute switch",
    "--force": "nothing here can be forced; a refusal is a result",
    "--retry": "a launch is never retried; an ambiguous outcome is recorded, not repeated",
    "--profile": "profiles are the actor's compiled constants, never an argument",
    "--aws-profile": "profiles are the actor's compiled constants, never an argument",
    "--skip-placement": "placement verification is not optional",
    "--no-cleanup": "the prescribed cleanup is not optional",
    "--task-arn": "the tool launches; it never adopts a task it did not start",
    "--release-reservation": "a reservation is never released; recovery records it",
}

#: Exit codes. Command status only -- never a data verdict, never task completion.
EXIT_PREPARED: Final = 0
EXIT_REFUSED_ARGUMENTS: Final = 2
EXIT_REFUSED_RECORDS: Final = 3
EXIT_REFUSED_AUTHORIZATION: Final = 4
EXIT_REFUSED_EQUIVALENCE: Final = 5
EXIT_REFUSED_CONTAINMENT: Final = 6
EXIT_REFUSED_DEPENDENCY: Final = 7
EXIT_REFUSED_BOOTSTRAP: Final = 8
EXIT_LAUNCH_TERMINAL: Final = 0
EXIT_LAUNCH_NOT_TERMINAL: Final = 9
EXIT_ROW_COMPLETED: Final = 0
EXIT_ROW_NOT_COMPLETED: Final = 10
EXIT_REFUSED_RESERVATION: Final = 11
EXIT_REFUSED_RECOVERY_PENDING: Final = 12
EXIT_REFUSED_LEDGER_LOCKED: Final = 13
EXIT_INTERRUPTED_AFTER_LAUNCH: Final = 14
EXIT_RECOVERED: Final = 0
EXIT_VERDICT_RECORDED: Final = 0
EXIT_REFUSED_LEGACY_RESERVATIONS: Final = 15
EXIT_COLLECTION_NOT_COLLECTED: Final = 16
EXIT_REFUSED_COLLECTION_RECORDS: Final = 17
EXIT_REFUSED_CONTRADICTION_UNRESOLVED: Final = 18
EXIT_REFUSED_RECEIPT_BINDING: Final = 19
#: The hand-read completion's acknowledgement of one recorded contradiction, by the
#: collection record's digest; repeatable; never accepted with a collection.
ACKNOWLEDGE_FLAG: Final = "--acknowledge-collection-contradiction"

_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")

#: Allowlisted output sentences. Nothing else reaches stdout.
SENTENCES: Final[dict[str, str]] = {
    "refused_arguments": "launch refused: the arguments were not admitted",
    "refused_records": "launch refused: an owner record was not admitted",
    "refused_authorization": "launch refused: no authorization for this launch specification",
    "refused_equivalence": "launch refused: the verification configuration is not equivalent",
    "refused_containment": "launch refused: the ledger and records must sit under the private root",
    "refused_dependency": "launch refused: a dependency could not be built",
    "refused_bootstrap": "launch refused: the human bootstrap did not prove an identity",
    "refused_reservation": "launch refused: the identity is already reserved",
    "refused_recovery_pending": "launch refused: an interrupted attempt awaits recovery",
    "refused_ledger_locked": "launch refused: the ledger is locked by another process",
    "refused_legacy_reservations": (
        "launch refused: first-revision reservations under the records directory must be moved"
        " beside the ledger by hand"
    ),
    "prepared": "launch prepared offline; no client was constructed and nothing was launched",
    "launched": "launch sequence finished; see the evidence document",
    "interrupted_after_launch": (
        "launch interrupted after the sequence began; the identity stays reserved -- recover"
    ),
    "row_completed": "ledger row completed from the verified receipt",
    "collection_not_collected": (
        "receipt not collected: the collection is recorded (outcome and counts, never log "
        "content), the row stays provisional, nothing is established about whether a "
        "receipt exists, and the next collection reads the stream again"
    ),
    "refused_collection_records": (
        "launch refused: the recorded collections of this launch are malformed, bound to "
        "another launch or stream, carry an unverifiable line, or contradict each other; "
        "nothing is chosen between them"
    ),
    "refused_contradiction_unresolved": (
        "launch refused: a recorded collection of this launch found contradictory receipts "
        "and no disposition names it; no collection resolves that -- the owner reads the "
        "stream, completes from a hand-read receipt and acknowledges the record by digest"
    ),
    "refused_receipt_binding": (
        "launch refused: a disposition bound this launch to one hand-read receipt; only a "
        "hand-read completion with that receipt continues, no other receipt does, and a "
        "collection does not"
    ),
    "refused_destination": (
        "launch refused: the registration names no log destination for this entry, or not "
        "this entry's"
    ),
    "row_not_completed": "ledger row not completed: the receipt establishes no disposition",
    "recovered": "interrupted attempt recorded; the identity is consumed and nothing was launched",
    "verdict_recorded": "isolation verdict recorded beside the launch record",
}

_ACTORS: Final = ("acquisition", "build")
_KINDS: Final = ("production", "verification")
#: The negative release modes of ADR-0047, admitted for a verification launch
#: only; the ordinary mode is the default and is never spelled on the command line.
_RELEASE_MODES: Final = ("withheld", "mismatched")


class LaunchRefusalError(Exception):
    """A closed refusal: one sentence key and one exit code. Carries no value."""

    def __init__(self, key: str, exit_code: int) -> None:
        super().__init__(key)
        self.key = key
        self.exit_code = exit_code


@dataclass(frozen=True, slots=True, kw_only=True)
class LaunchArguments:
    """The admitted arguments. Paths are the owner's; nothing else is a value."""

    actor: str
    kind: str
    identity: str
    ledger: Path
    launch_inputs: Path
    records_dir: Path
    authorization: Path | None
    slice_path: Path | None
    run_identities: tuple[str, ...]
    production_configuration: Path | None
    verification_configuration: Path | None
    acquisition_configuration: Path | None
    authorized: bool
    complete_row: bool
    recover: bool
    isolation_verdict: bool
    launch_record: Path | None
    receipt_lines: Path | None
    reachability_evidence: Path | None
    #: ``None`` is the ordinary release; a negative mode names the R-1 cell it produces.
    release_mode: str | None = None
    #: ``--complete-row --collect-receipt``: the receipt read from the launch's own stream
    #: (ADR-0049 s.2) instead of a hand-read file; needs :data:`COLLECT_FLAG`.
    collect_receipt: bool = False
    collection_authorized: bool = False
    #: ``--acknowledge-collection-contradiction <sha256>`` (repeatable): the hand-read
    #: completion's explicit disposition of recorded contradictions (ADR-0049 s.2.5).
    acknowledged_contradictions: tuple[str, ...] = ()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="production_launch",
        description="one authorized production or verification launch; refuses by default",
        add_help=True,
    )
    parser.add_argument("--actor", choices=_ACTORS, required=True)
    parser.add_argument("--kind", choices=_KINDS, required=True)
    parser.add_argument("--identity", required=True, help="the run or build identity")
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--launch-inputs", required=True, type=Path)
    parser.add_argument("--records-dir", required=True, type=Path)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--slice", dest="slice_path", type=Path)
    parser.add_argument("--run-identity", dest="run_identities", action="append", default=[])
    parser.add_argument("--production-configuration", type=Path)
    parser.add_argument("--verification-configuration", type=Path)
    parser.add_argument("--acquisition-configuration", type=Path)
    parser.add_argument(AUTHORIZATION_FLAG, dest="authorized", action="store_true")
    parser.add_argument("--complete-row", action="store_true")
    parser.add_argument("--recover", action="store_true")
    parser.add_argument("--isolation-verdict", action="store_true")
    parser.add_argument("--launch-record", type=Path)
    parser.add_argument("--receipt-lines", type=Path)
    parser.add_argument("--reachability-evidence", type=Path)
    parser.add_argument("--release-mode", choices=_RELEASE_MODES)
    parser.add_argument("--collect-receipt", action="store_true")
    parser.add_argument(COLLECT_FLAG, dest="collection_authorized", action="store_true")
    parser.add_argument(
        ACKNOWLEDGE_FLAG, dest="acknowledged_contradictions", action="append", default=[]
    )
    return parser


def parse_arguments(argv: Sequence[str]) -> LaunchArguments:
    """Admit the arguments or refuse. A refused spelling is refused before parsing."""
    for token in argv:
        name = token.split("=", 1)[0]
        if name in REFUSED_FLAGS:
            raise LaunchRefusalError("refused_arguments", EXIT_REFUSED_ARGUMENTS)
    parser = _parser()
    try:
        namespace = parser.parse_args(list(argv))
    except SystemExit:
        raise LaunchRefusalError("refused_arguments", EXIT_REFUSED_ARGUMENTS) from None
    arguments = LaunchArguments(
        actor=namespace.actor,
        kind=namespace.kind,
        identity=namespace.identity,
        ledger=namespace.ledger,
        launch_inputs=namespace.launch_inputs,
        records_dir=namespace.records_dir,
        authorization=namespace.authorization,
        slice_path=namespace.slice_path,
        run_identities=tuple(namespace.run_identities),
        production_configuration=namespace.production_configuration,
        verification_configuration=namespace.verification_configuration,
        acquisition_configuration=namespace.acquisition_configuration,
        authorized=bool(namespace.authorized),
        complete_row=bool(namespace.complete_row),
        recover=bool(namespace.recover),
        isolation_verdict=bool(namespace.isolation_verdict),
        launch_record=namespace.launch_record,
        receipt_lines=namespace.receipt_lines,
        reachability_evidence=namespace.reachability_evidence,
        release_mode=namespace.release_mode,
        collect_receipt=bool(namespace.collect_receipt),
        collection_authorized=bool(namespace.collection_authorized),
        acknowledged_contradictions=tuple(namespace.acknowledged_contradictions),
    )
    # An acknowledgement belongs to a hand-read completion only, and names a digest.
    if arguments.acknowledged_contradictions and (
        not arguments.complete_row
        or arguments.receipt_lines is None
        or any(_SHA256_RE.fullmatch(d) is None for d in arguments.acknowledged_contradictions)
    ):
        raise LaunchRefusalError("refused_arguments", EXIT_REFUSED_ARGUMENTS)
    modes = sum((arguments.complete_row, arguments.recover, arguments.isolation_verdict))
    if modes > 1 or (modes == 1 and arguments.authorized):
        raise LaunchRefusalError("refused_arguments", EXIT_REFUSED_ARGUMENTS)
    # Collection is a completion from the launch's own stream: --complete-row with the
    # collection flag, no hand-read file, no other mode and no launch flag.
    if arguments.collect_receipt != arguments.collection_authorized or (
        arguments.collect_receipt
        and (not arguments.complete_row or arguments.receipt_lines is not None)
    ):
        raise LaunchRefusalError("refused_arguments", EXIT_REFUSED_ARGUMENTS)
    # A negative release mode is a verification launch's (preparation or execution)
    # and no other mode's; the production kind never carries one.
    if arguments.release_mode is not None and (modes or arguments.kind != "verification"):
        raise LaunchRefusalError("refused_arguments", EXIT_REFUSED_ARGUMENTS)
    if arguments.complete_row or arguments.isolation_verdict:
        if arguments.launch_record is None or (
            arguments.receipt_lines is None and not arguments.collect_receipt
        ):
            raise LaunchRefusalError("refused_arguments", EXIT_REFUSED_ARGUMENTS)
        if arguments.isolation_verdict and arguments.verification_configuration is None:
            raise LaunchRefusalError("refused_arguments", EXIT_REFUSED_ARGUMENTS)
        return arguments
    if arguments.reachability_evidence is not None:
        raise LaunchRefusalError("refused_arguments", EXIT_REFUSED_ARGUMENTS)
    if arguments.recover:
        return arguments
    acquisition = arguments.actor == "acquisition"
    if acquisition and (arguments.slice_path is None or arguments.run_identities):
        raise LaunchRefusalError("refused_arguments", EXIT_REFUSED_ARGUMENTS)
    if not acquisition and (
        arguments.slice_path is not None
        # ADR-0045 s.11: a build VERIFICATION launch may name no run; a production
        # build must name at least one.
        or (not arguments.run_identities and arguments.kind != "verification")
    ):
        raise LaunchRefusalError("refused_arguments", EXIT_REFUSED_ARGUMENTS)
    if arguments.kind == "verification":
        if (
            arguments.production_configuration is None
            or arguments.verification_configuration is None
        ):
            raise LaunchRefusalError("refused_arguments", EXIT_REFUSED_ARGUMENTS)
        if not acquisition and arguments.acquisition_configuration is None:
            raise LaunchRefusalError("refused_arguments", EXIT_REFUSED_ARGUMENTS)
    elif (
        arguments.production_configuration is not None
        or arguments.verification_configuration is not None
        or arguments.acquisition_configuration is not None
    ):
        raise LaunchRefusalError("refused_arguments", EXIT_REFUSED_ARGUMENTS)
    if arguments.authorized and arguments.authorization is None:
        raise LaunchRefusalError("refused_arguments", EXIT_REFUSED_ARGUMENTS)
    return arguments


# ---------------------------------------------------------------------------
# Offline preparation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class PreparedLaunch:
    """Everything the authorized branch needs, computed offline. Never rendered."""

    actor: Any
    kind: Any
    entry: Any
    compiled: Any
    target: Any
    specification: Any
    authorization: Any
    ledger: Any
    slice: Any
    plan_digest: str | None
    equivalence: str | None

    def __repr__(self) -> str:
        """A fixed token."""
        return "PreparedLaunch(<private>)"

    def summary(self) -> tuple[str, ...]:
        """Sanitized lines: actor, kind, entry, sizes, the specification digest, equivalence."""
        lines = [
            f"actor={self.actor.value} kind={self.kind.value} entry={self.entry.value}",
            f"input_bytes={len(self.authorization.input_bytes)} "
            f"ledger_rows={len(self.ledger.rows)}",
            f"specification_digest={self.specification.digest}",
        ]
        if self.equivalence is not None:
            lines.append(f"equivalence={self.equivalence}")
        return tuple(lines)


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None


def _contained(path: Path, root: Path) -> bool:
    """Whether ``path`` resolves beneath ``root``. Nothing is created or listed."""
    try:
        resolved = path.resolve(strict=False)
        return resolved == root.resolve() or root.resolve() in resolved.parents
    except OSError:
        return False


def _private_root(root_source: Callable[[], Path] | None) -> Path:
    from kalpamani.data.qualify.sharadar.runtime_binding import private_root

    try:
        return (private_root if root_source is None else root_source)()
    except Exception:
        raise LaunchRefusalError("refused_containment", EXIT_REFUSED_CONTAINMENT) from None


def _store(arguments: LaunchArguments, root: Path) -> Any:
    """The launch store, after containment: the ledger and records under the private root.

    The store anchors reservations and the lock to the ledger's canonical path; the
    records directory only receives evidence. First-revision reservations under the
    supplied records directory refuse until the owner has moved them.
    """
    from kalpamani.data.production.sharadar.launch_store import LaunchStore, StoreError

    if not _contained(arguments.ledger, root) or not _contained(arguments.records_dir, root):
        raise LaunchRefusalError("refused_containment", EXIT_REFUSED_CONTAINMENT)
    store = LaunchStore(ledger_path=arguments.ledger, records_dir=arguments.records_dir)
    try:
        store.refuse_legacy_state()
    except StoreError:
        raise LaunchRefusalError(
            "refused_legacy_reservations", EXIT_REFUSED_LEGACY_RESERVATIONS
        ) from None
    return store


def prepare_launch(
    arguments: LaunchArguments,
    *,
    now: datetime,
    root_source: Callable[[], Path] | None = None,
) -> PreparedLaunch:
    """Parse every record, build the specification, materialize the input, compile. **Offline.**

    Raises :class:`LaunchRefusalError` with a closed key; never a value.
    """
    from kalpamani.data.production.sharadar import launch_records as lr
    from kalpamani.data.production.sharadar.launch_store import StoreError
    from kalpamani.data.production.sharadar.launcher import LaunchAuthorization
    from kalpamani.data.production.sharadar.vocabulary import ProductionActor

    actor = ProductionActor(arguments.actor)
    kind = lr.LaunchKind(arguments.kind)
    store = _store(arguments, _private_root(root_source))
    try:
        ledger, _ = store.read_ledger()
        # Interrupted work is reconciled before anything else is prepared: a reservation
        # with no ledger row is an identity the ledger cannot yet see.
        if store.unreconciled(ledger):
            raise LaunchRefusalError("refused_recovery_pending", EXIT_REFUSED_RECOVERY_PENDING)
    except StoreError:
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
    try:
        inputs = lr.parse_launch_inputs(_read(arguments.launch_inputs))
        slice_document: Any = None
        run_identities: list[str] | None = None
        if actor is ProductionActor.ACQUISITION:
            from kalpamani.data.production.sharadar.documents import decode_document

            assert arguments.slice_path is not None
            slice_document = decode_document(
                _read(arguments.slice_path), max_bytes=lr.MAX_RECORD_BYTES
            )
        else:
            run_identities = list(arguments.run_identities)
        specification = lr.build_specification(
            ledger=ledger,
            inputs=inputs,
            actor=actor,
            kind=kind,
            identity=arguments.identity,
            slice_document=slice_document,
            run_identities=run_identities,
            release_mode=(
                lr.ReleaseMode.NORMAL
                if arguments.release_mode is None
                else lr.ReleaseMode(arguments.release_mode.upper())
            ),
        )
        covered: Any = None
        plan_digest: str | None = None
        if actor is ProductionActor.ACQUISITION:
            from kalpamani.data.production.sharadar.inputs import parse_slice

            input_bytes = lr.materialize_acquisition_input(
                ledger,
                identity=arguments.identity,
                kind=kind,
                slice_document=slice_document,
                now=now,
            )
            covered = parse_slice(slice_document)
            plan_digest = specification.workload["plan_digest"]
        else:
            input_bytes = lr.materialize_build_input(
                ledger,
                identity=arguments.identity,
                kind=kind,
                run_identities=list(arguments.run_identities),
                now=now,
            )
        compiled, target = lr.compile_launch(inputs, actor=actor, kind=kind)
    except (lr.LaunchRecordError, Exception):
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None

    equivalence: str | None = None
    if kind is lr.LaunchKind.VERIFICATION:
        assert arguments.production_configuration is not None
        assert arguments.verification_configuration is not None
        acquisition = (
            None
            if arguments.acquisition_configuration is None
            else _read(arguments.acquisition_configuration)
        )
        verdict = lr.configuration_equivalence(
            inputs,
            actor=actor,
            production=_read(arguments.production_configuration),
            verification=_read(arguments.verification_configuration),
            acquisition=acquisition,
        )
        equivalence = verdict.value
        if verdict is not lr.EquivalenceVerdict.EQUIVALENT:
            raise LaunchRefusalError("refused_equivalence", EXIT_REFUSED_EQUIVALENCE)

    authorization = LaunchAuthorization(identity=arguments.identity, input_bytes=input_bytes)
    return PreparedLaunch(
        actor=actor,
        kind=kind,
        entry=specification.entry,
        compiled=compiled,
        target=target,
        specification=specification,
        authorization=authorization,
        ledger=ledger,
        slice=covered,
        plan_digest=plan_digest,
        equivalence=equivalence,
    )


def write_specification(
    arguments: LaunchArguments, prepared: PreparedLaunch, *, now: datetime
) -> Path:
    """Write the reviewable specification to the records directory; the owner authorizes it."""
    from kalpamani.data.production.sharadar.launch_store import LaunchStore, StoreError

    store = LaunchStore(ledger_path=arguments.ledger, records_dir=arguments.records_dir)
    try:
        path: Path = store.write_record(
            "launch-specification", prepared.specification.document(), at=now
        )
    except StoreError:
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
    return path


def admit_authorization(
    arguments: LaunchArguments, prepared: PreparedLaunch, *, now: datetime
) -> Any:
    """The owner's written authorization for THIS specification, valid now, or refuse."""
    from kalpamani.data.production.sharadar import launch_records as lr

    if arguments.authorization is None:
        raise LaunchRefusalError("refused_authorization", EXIT_REFUSED_AUTHORIZATION)
    try:
        return lr.parse_authorization(
            _read(arguments.authorization),
            actor=prepared.actor,
            kind=prepared.kind,
            identity=arguments.identity,
            specification_digest=prepared.specification.digest,
            now=now,
        )
    except lr.LaunchRecordError:
        raise LaunchRefusalError("refused_authorization", EXIT_REFUSED_AUTHORIZATION) from None


# ---------------------------------------------------------------------------
# The authorized branch
# ---------------------------------------------------------------------------


class ClientFactory(Protocol):
    """The four client-shaped objects the launch needs, each under a named profile.

    The real factory (:class:`_Boto3Clients`) builds SDK clients only inside the
    authorized branch; every test injects fakes.
    """

    def sts(self, profile: str) -> Any:
        """A client with ``get_caller_identity``."""
        ...

    def ecs(self, profile: str) -> Any:
        """A client with ``run_task``, ``describe_tasks`` and ``stop_task``."""
        ...

    def ec2(self, profile: str) -> Any:
        """A client with ``describe_network_interfaces``."""
        ...

    def ssm(self, profile: str) -> Any:
        """A client with ``get_parameter``, ``put_parameter`` and ``delete_parameter``."""
        ...

    def logs(self, profile: str) -> Any:
        """A client with ``get_log_events`` (the receipt collector's one operation)."""
        ...


def workstation_client_config() -> dict[str, object]:
    """The botocore ``Config`` arguments for every workstation client. Pure.

    The same finite socket timeouts and **one attempt in total** as a task's SSM and STS
    clients: a hidden SDK retry of ``RunTask`` would be a second launch, of a parameter
    write a second create, of ``DescribeTasks`` an observation the ceiling never counted.
    """
    from kalpamani.data.production.sharadar.task_clients import TaskService, client_config_kwargs

    return client_config_kwargs(TaskService.SSM)


class _Boto3Clients:
    """Real clients from a profile-pinned SDK session. Constructed only when authorized."""

    __slots__ = ("_sessions",)

    def __init__(self) -> None:
        self._sessions: dict[str, Any] = {}

    def _client(self, profile: str, service: str) -> Any:
        import boto3  # type: ignore[import-untyped]
        from botocore.config import Config  # type: ignore[import-untyped]

        from kalpamani.data.production.sharadar.task_clients import sts_endpoint_url
        from kalpamani.data.production.sharadar.vocabulary import EXPECTED_REGION

        if profile not in self._sessions:
            self._sessions[profile] = boto3.Session(
                profile_name=profile, region_name=EXPECTED_REGION
            )
        kwargs: dict[str, Any] = {
            "service_name": service,
            "region_name": EXPECTED_REGION,
            "config": Config(**workstation_client_config()),
        }
        if service == "sts":
            kwargs["endpoint_url"] = sts_endpoint_url()
        return self._sessions[profile].client(**kwargs)

    def sts(self, profile: str) -> Any:
        return self._client(profile, "sts")

    def ecs(self, profile: str) -> Any:
        return self._client(profile, "ecs")

    def ec2(self, profile: str) -> Any:
        return self._client(profile, "ec2")

    def ssm(self, profile: str) -> Any:
        return self._client(profile, "ssm")

    def logs(self, profile: str) -> Any:
        # The same config: one attempt in total (effective SDK retries 0), finite timeouts.
        return self._client(profile, "logs")


@dataclass(frozen=True, slots=True, kw_only=True)
class LaunchResult:
    """What the authorized branch produced: the report, the row written, the files."""

    report: Any
    ledger_outcome: str
    evidence_path: Path
    record_path: Path | None

    def __repr__(self) -> str:
        """Outcome tokens only."""
        return f"LaunchResult(outcome={self.report.outcome.value!r}, row={self.ledger_outcome!r})"


def reserve_identity(
    arguments: LaunchArguments,
    prepared: PreparedLaunch,
    *,
    now: Callable[[], datetime],
    root_source: Callable[[], Path] | None = None,
) -> Any:
    """Consume the identity durably and exclusively, bound to the specification, or refuse.

    Under the ledger lock: the ledger is re-read (a concurrent attempt may have written
    it since preparation), the identity re-checked against it and against the ledger's
    reservations, and the reservation -- carrying the whole authorized specification --
    created with exclusive semantics beside the ledger, **before** any bootstrap, client
    or external mutation. A reservation that cannot be persisted refuses; one that
    already exists refuses; neither launches.
    """
    from kalpamani.data.production.sharadar import launch_records as lr
    from kalpamani.data.production.sharadar.launch_store import (
        Reservation,
        StoreDefect,
        StoreError,
    )

    store = _store(arguments, _private_root(root_source))
    try:
        with store.locked(now=now):
            ledger, _ = store.read_ledger()
            if store.unreconciled(ledger):
                raise LaunchRefusalError("refused_recovery_pending", EXIT_REFUSED_RECOVERY_PENDING)
            try:
                lr.admit_identity(ledger, arguments.identity, kind=prepared.kind)
            except lr.LaunchRecordError:
                raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
            if store.reservation(arguments.identity) is not None:
                raise LaunchRefusalError("refused_reservation", EXIT_REFUSED_RESERVATION)
            store.reserve(
                Reservation(
                    identity=arguments.identity,
                    actor=prepared.actor,
                    kind=prepared.kind,
                    specification=prepared.specification,
                    reserved_at=now(),
                )
            )
    except StoreError as error:
        if error.defect is StoreDefect.LEDGER_LOCKED:
            raise LaunchRefusalError("refused_ledger_locked", EXIT_REFUSED_LEDGER_LOCKED) from None
        if error.defect is StoreDefect.RESERVATION_EXISTS:
            raise LaunchRefusalError("refused_reservation", EXIT_REFUSED_RESERVATION) from None
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
    return store


def execute_launch(
    arguments: LaunchArguments,
    prepared: PreparedLaunch,
    *,
    store: Any,
    authorization_record: Any,
    clients: ClientFactory,
    environment: Callable[[str], str | None],
    now: Callable[[], datetime],
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
    root_source: Callable[[], Path] | None = None,
    security_of: Callable[[Path], Any] | None = None,
    while_running: Callable[[Any], None] | None = None,
) -> LaunchResult:
    """The authorized branch, after the reservation: two bootstraps, one launch, the records.

    ``while_running`` is handed to the launcher unchanged (ADR-0045 s.12): it is admitted
    for a released permission-probe or build verification launch alone, and for any
    other launch the tool refuses before its first bootstrap -- ``refused_arguments`` --
    rather than letting the launcher raise.

    The human bootstrap runs under the actor's human profile and again under its
    launcher profile, each proving its own identity against the same private binding
    file before any parameter or ECS call; the launcher's before-and-after proofs then
    call STS under the profile the path names. The authorization's freshness is checked
    once more immediately before the launch. Records and the ledger row are written
    afterwards under names that cannot collide and under the ledger lock; a failure to
    write any of them leaves the reservation in place, so the identity is never reusable.
    """
    from kalpamani.data.production.sharadar import launch_records as lr
    from kalpamani.data.production.sharadar.compute import Ec2InterfaceAdapter, EcsTaskAdapter
    from kalpamani.data.production.sharadar.identity import (
        ProvenIdentity,
        production_identity_refusal,
    )
    from kalpamani.data.production.sharadar.inputs import input_digest
    from kalpamani.data.production.sharadar.launch_store import StoreDefect, StoreError
    from kalpamani.data.production.sharadar.launcher import (
        LaunchAdapters,
        admits_while_running,
        launch_authorized_run,
    )
    from kalpamani.data.production.sharadar.outcomes import LaunchOutcome
    from kalpamani.data.production.sharadar.parameters import SsmParameterAdapter
    from kalpamani.data.production.sharadar.runner import HumanBootstrapOutcome, human_bootstrap
    from kalpamani.data.production.sharadar.vocabulary import IdentityPath, constants_for

    if while_running is not None and not admits_while_running(
        prepared.compiled, prepared.authorization, prepared.specification.release_mode
    ):
        raise LaunchRefusalError("refused_arguments", EXIT_REFUSED_ARGUMENTS)
    actor = prepared.actor
    constants = constants_for(actor)
    profile_of = {
        IdentityPath.HUMAN: constants.profile,
        IdentityPath.LAUNCHER: constants.launcher_profile,
    }

    def caller_identity_under(path: IdentityPath) -> Callable[[], object]:
        def call() -> object:
            return clients.sts(profile_of[path]).get_caller_identity()

        return call

    binding: Any = None
    for path in (IdentityPath.HUMAN, IdentityPath.LAUNCHER):
        bootstrap = human_bootstrap(
            actor=actor,
            path=path,
            environment=environment,
            caller_identity=caller_identity_under(path),
            root_source=root_source,
            security_of=security_of,
        )
        if bootstrap.outcome is not HumanBootstrapOutcome.IDENTITY_PROVEN:
            raise LaunchRefusalError("refused_bootstrap", EXIT_REFUSED_BOOTSTRAP)
        binding = bootstrap.binding

    def identity_proof(path: IdentityPath) -> str | None:
        verdict = production_identity_refusal(
            actor, path=path, binding=binding, caller_identity=caller_identity_under(path)
        )
        return None if isinstance(verdict, ProvenIdentity) else verdict

    try:
        adapters = LaunchAdapters(
            ecs=EcsTaskAdapter(
                ecs=clients.ecs(constants.launcher_profile), compiled=prepared.compiled
            ),
            ec2=Ec2InterfaceAdapter(ec2=clients.ec2(constants.launcher_profile)),
            human_parameters=SsmParameterAdapter(ssm=clients.ssm(constants.profile)),
            launcher_parameters=SsmParameterAdapter(ssm=clients.ssm(constants.launcher_profile)),
        )
    except Exception:
        raise LaunchRefusalError("refused_dependency", EXIT_REFUSED_DEPENDENCY) from None

    # Freshness, revalidated immediately before the first external mutation.
    launched_at = now()
    if not authorization_record.valid_at(launched_at):
        raise LaunchRefusalError("refused_authorization", EXIT_REFUSED_AUTHORIZATION)
    # The release behaviour is the authorized specification's -- the digest the
    # authorization named covers it -- never the command line's.
    report = launch_authorized_run(
        compiled=prepared.compiled,
        adapters=adapters,
        authorization=prepared.authorization,
        identity_proof=identity_proof,
        now=now,
        monotonic=monotonic,
        sleep=sleep,
        release_mode=prepared.specification.release_mode,
        while_running=while_running,
    )
    recorded_at = now()

    outcome = lr.provisional_ledger_outcome(
        kind=prepared.kind,
        task_started=report.task_started,
        misplaced=report.outcome is LaunchOutcome.MISPLACED,
        exit_codes=report.task_exit_codes,
    )
    record: Any = None
    if report.handle is not None:
        record = lr.LaunchRecord(
            entry=prepared.entry,
            kind=prepared.kind,
            identity=arguments.identity,
            task_arn=report.handle.task_arn,
            task_definition_arn=prepared.compiled.task_definition_arn,
            image_digest=prepared.compiled.image_digest,
            configuration_digest=prepared.compiled.configuration_digest,
            code_commit=prepared.target.code_commit,
            input_digest=input_digest(prepared.authorization.input_bytes),
            slice=prepared.slice,
            plan_digest=prepared.plan_digest,
            launched_at=launched_at,
            recorded_at=recorded_at,
            network_interface_id=report.network_interface_id,
            subnet_id=report.subnet_id,
            security_group_ids=report.security_group_ids,
            specification_digest=prepared.specification.digest,
            release_mode=report.release_mode,
            observed_exit_code=report.observed_exit_code,
        )
        row = lr.provisional_ledger_row(record, outcome=outcome, completed_at=recorded_at)
    else:
        row = lr.OwnerLedgerRow(
            identity=arguments.identity,
            actor=actor,
            kind=prepared.kind,
            outcome=outcome,
            evidence=lr.LedgerEvidence.EXIT_CODE_ONLY,
            launched_at=launched_at,
            completed_at=recorded_at,
            slice=prepared.slice,
            plan_digest=prepared.plan_digest,
        )
    evidence = lr.evidence_document(
        actor=actor,
        kind=prepared.kind,
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
    # Records first, the ledger last, all under the lock; every name is exclusive. A
    # failure anywhere here leaves the reservation, which is what makes the identity
    # unrepeatable: the owner recovers, and nothing is launched twice.
    try:
        with store.locked(now=now):
            ledger, digest = store.read_ledger()
            ledger = lr.append_row(ledger, row)
            evidence_path: Path = store.write_record("launch-evidence", evidence, at=recorded_at)
            record_path: Path | None = None
            if record is not None:
                record_path = store.write_record("launch-record", record.document(), at=recorded_at)
            store.replace_ledger(ledger, expected_digest=digest)
    except (StoreError, lr.LaunchRecordError) as error:
        defect = getattr(error, "defect", None)
        if defect is StoreDefect.LEDGER_LOCKED:
            raise LaunchRefusalError("refused_ledger_locked", EXIT_REFUSED_LEDGER_LOCKED) from None
        raise LaunchRefusalError(
            "interrupted_after_launch", EXIT_INTERRUPTED_AFTER_LAUNCH
        ) from None
    return LaunchResult(
        report=report, ledger_outcome=outcome, evidence_path=evidence_path, record_path=record_path
    )


# ---------------------------------------------------------------------------
# Row completion, recovery, and the isolation verdict
# ---------------------------------------------------------------------------


def _record_and_receipt(
    arguments: LaunchArguments,
    *,
    root_source: Callable[[], Path] | None,
    receipt_text: str | None = None,
) -> tuple[Any, Any, Any]:
    """The store, the launch record and the receipt verified against it, or refuse.

    The receipt lines come from the hand-read file, or -- ``receipt_text`` -- from the
    collector, and pass through exactly the same verifier and the same binding rules.
    """
    from kalpamani.data.production.sharadar import launch_records as lr
    from kalpamani.data.production.sharadar.receipts import ReceiptError, collect_and_verify

    assert arguments.launch_record is not None
    assert arguments.receipt_lines is not None or receipt_text is not None
    root = _private_root(root_source)
    if not _contained(arguments.launch_record, root):
        raise LaunchRefusalError("refused_containment", EXIT_REFUSED_CONTAINMENT)
    store = _store(arguments, root)
    try:
        record = lr.parse_launch_record(_read(arguments.launch_record))
    except lr.LaunchRecordError:
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
    if (
        record.identity != arguments.identity
        or record.kind.value != arguments.kind
        or record.actor.value != arguments.actor
    ):
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS)
    _bound_reservation(store, record)
    if receipt_text is None:
        assert arguments.receipt_lines is not None
        try:
            text = _read(arguments.receipt_lines).decode("utf-8")
        except UnicodeDecodeError:
            raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
    else:
        text = receipt_text
    try:
        verified = collect_and_verify(text.splitlines(), expectation=record.expectation())
    except ReceiptError:
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
    return store, record, verified


def _registered_destination(arguments: LaunchArguments, record: Any) -> Any:
    """The log destination the registration names for this launch's entry, or refuse."""
    from kalpamani.data.production.sharadar import launch_records as lr
    from kalpamani.data.production.sharadar.receipt_collector import (
        CollectorError,
        destination_for,
    )

    try:
        inputs = lr.parse_launch_inputs(_read(arguments.launch_inputs))
    except lr.LaunchRecordError:
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
    target = inputs.targets.get((record.actor, record.kind))
    if target is None or target.task_definition_arn != record.task_definition_arn:
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS)
    try:
        return destination_for(record.entry, target.task_definition.log_destination)
    except CollectorError:
        raise LaunchRefusalError("refused_destination", EXIT_REFUSED_RECORDS) from None


def collect_receipt_lines(
    arguments: LaunchArguments,
    *,
    clients: ClientFactory,
    environment: Callable[[str], str | None],
    now: Callable[[], datetime],
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
    root_source: Callable[[], Path] | None,
    security_of: Callable[[Path], Any] | None,
) -> str:
    """The launch's receipt line from its own stream (ADR-0049 s.2), or refuse.

    The launch record (bound to its reservation), the registered destination held to the
    record's entry, the launcher identity proven through the accepted human bootstrap, then
    one bounded collection under that profile -- recorded as a collection record whatever
    its outcome, the line kept only once it verified against this launch record. The
    collection is refused until the launcher observed the task's terminal state (a
    stopped task writes nothing more; delivery lag is the collector's stated limit).
    Every collection record about this launch is admitted through the collector's one
    rule (:func:`admit_collection_records`): a verified COLLECTED line is reused and the
    stream is not read again (repeatable completion); a rejected, exhausted, incomplete
    or contradictory attempt never blocks, and the stream is read again; malformed,
    misbound, unverifiable or mutually contradictory records refuse, and nothing is
    chosen between them. Anything short of COLLECTED leaves the row provisional and
    establishes nothing about whether a receipt exists.
    """
    from kalpamani.data.production.sharadar import launch_records as lr
    from kalpamani.data.production.sharadar.launch_store import StoreError
    from kalpamani.data.production.sharadar.receipt_collector import (
        CollectionRecordDefect,
        CollectionRecordError,
        SdkLogsClient,
        admit_collection_records,
        collect_receipt,
    )
    from kalpamani.data.production.sharadar.runner import HumanBootstrapOutcome, human_bootstrap
    from kalpamani.data.production.sharadar.vocabulary import IdentityPath, constants_for

    assert arguments.launch_record is not None
    root = _private_root(root_source)
    if not _contained(arguments.launch_record, root):
        raise LaunchRefusalError("refused_containment", EXIT_REFUSED_CONTAINMENT)
    store = _store(arguments, root)
    try:
        record = lr.parse_launch_record(_read(arguments.launch_record))
    except lr.LaunchRecordError:
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
    if (
        record.identity != arguments.identity
        or record.kind.value != arguments.kind
        or record.actor.value != arguments.actor
    ):
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS)
    _bound_reservation(store, record)
    if record.observed_exit_code is None:
        # No collection before the launcher observed the terminal state.
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS)
    try:
        ledger, _digest = store.read_ledger()
    except StoreError:
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
    row = ledger.row(record.identity)
    if row is None or row.evidence is not lr.LedgerEvidence.EXIT_CODE_ONLY:
        # No collection for a row that is not provisional: nothing to complete, no read.
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS)
    destination = _registered_destination(arguments, record)
    from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex

    record_digest = sha256_hex(canonical_bytes(record.document()))
    expectation = record.expectation()
    # Every collection record about this launch, under the collector's one rule.
    try:
        admission = admit_collection_records(
            _collection_payloads(arguments.records_dir),
            identity=record.identity,
            launch_record_sha256=record_digest,
            destination=destination,
            task_id=record.task_id,
            expectation=expectation,
        )
    except CollectionRecordError as error:
        if error.defect is CollectionRecordDefect.CONTRADICTION_UNRESOLVED:
            raise LaunchRefusalError(
                "refused_contradiction_unresolved", EXIT_REFUSED_CONTRADICTION_UNRESOLVED
            ) from None
        if error.defect is CollectionRecordDefect.RECEIPT_SUBSTITUTED:
            raise LaunchRefusalError(
                "refused_receipt_binding", EXIT_REFUSED_RECEIPT_BINDING
            ) from None
        raise LaunchRefusalError(
            "refused_collection_records", EXIT_REFUSED_COLLECTION_RECORDS
        ) from None
    except OSError:
        raise LaunchRefusalError(
            "refused_collection_records", EXIT_REFUSED_COLLECTION_RECORDS
        ) from None
    if admission.reusable_line is not None:
        return admission.reusable_line
    if admission.bound_receipt_sha256 is not None:
        # A resolution begun by a hand-read completion is finished by one: no read.
        raise LaunchRefusalError("refused_receipt_binding", EXIT_REFUSED_RECEIPT_BINDING)
    constants = constants_for(record.actor)
    bootstrap = human_bootstrap(
        actor=record.actor,
        path=IdentityPath.LAUNCHER,
        environment=environment,
        caller_identity=lambda: clients.sts(constants.launcher_profile).get_caller_identity(),
        root_source=root_source,
        security_of=security_of,
    )
    if bootstrap.outcome is not HumanBootstrapOutcome.IDENTITY_PROVEN:
        raise LaunchRefusalError("refused_bootstrap", EXIT_REFUSED_BOOTSTRAP)
    try:
        client = SdkLogsClient(lambda _service: clients.logs(constants.launcher_profile))
    except Exception:
        raise LaunchRefusalError("refused_dependency", EXIT_REFUSED_DEPENDENCY) from None
    collected = collect_receipt(
        destination=destination,
        task_id=record.task_id,
        expectation=expectation,
        client=client,
        now=now,
        monotonic=monotonic,
        sleep=sleep,
    )
    try:
        store.write_record(
            "receipt-collection",
            collected.document(identity=record.identity, launch_record_sha256=record_digest),
            at=collected.finished_at,
        )
    except StoreError:
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
    _emit([collected.summary()])
    if collected.receipt_line is None:
        raise LaunchRefusalError("collection_not_collected", EXIT_COLLECTION_NOT_COLLECTED)
    return collected.receipt_line


def _bound_reservation(store: Any, record: Any) -> Any:
    """The reservation this launch record belongs to, or refuse.

    The record names the specification digest the authorization named; the reservation
    beside the ledger carries that specification. They bind under the one shared rule
    (:func:`launch_store.bind_record`): the digests agree, the record's slice and plan
    digest are exactly the specification's workload, its target is the specification's
    own -- the revision, image, configuration and commit it registered -- and its
    verified placement is the specification's subnet and security groups as a set. A
    missing reservation, a different specification, another workload or a placement the
    specification did not name is not this launch, and refuses.
    """
    from kalpamani.data.production.sharadar.launch_store import (
        RecordBinding,
        StoreError,
        bind_record,
    )

    try:
        reservation = store.reservation(record.identity)
    except StoreError:
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
    if reservation is None:
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS)
    if bind_record(reservation, record) is not RecordBinding.BOUND:
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS)
    return reservation


def complete_row(
    arguments: LaunchArguments,
    *,
    now: Callable[[], datetime],
    root_source: Callable[[], Path] | None = None,
    receipt_text: str | None = None,
) -> bool:
    """Verify the hand-read receipt against the launch record and complete the row.

    Under the ledger lock and through the atomic replacement, like every ledger write.
    Returns ``True`` when the row was completed, ``False`` when the verified receipt
    establishes no disposition (the row stays provisional). A receipt that does not
    belong to the record refuses as a record refusal.
    """
    from kalpamani.data.production.sharadar import launch_records as lr
    from kalpamani.data.production.sharadar.launch_store import StoreDefect, StoreError

    store, record, verified = _record_and_receipt(
        arguments, root_source=root_source, receipt_text=receipt_text
    )
    # The receipt's outcome is the exit the launcher observed at the terminal state: two
    # pieces of evidence for one launch that disagree complete nothing.
    from kalpamani.data.production.sharadar.entry import EXIT_STATUS

    if (
        record.observed_exit_code is not None
        and EXIT_STATUS.get(verified.outcome) != record.observed_exit_code
    ):
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS)
    dispositions: list[dict[str, Any]] = []
    if receipt_text is None:
        # A hand-read completion over a recorded, unresolved contradiction needs the
        # owner's explicit acknowledgement of that record; it is then disposed, bound to
        # this receipt, and the contradiction record stays exactly as written.
        assert arguments.receipt_lines is not None
        dispositions = _dispositions_for(
            arguments, record, receipt_lines=_read(arguments.receipt_lines), now=now
        )
    try:
        with store.locked(now=now):
            ledger, digest = store.read_ledger()
            existing = ledger.row(record.identity)
            if existing is None or existing.evidence is not lr.LedgerEvidence.EXIT_CODE_ONLY:
                raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS)
            for document in dispositions:
                store.write_record("collection-disposition", document, at=now())
            try:
                completed = lr.complete_ledger_row(ledger, record=record, receipt=verified)
            except lr.LaunchRecordError as error:
                if error.defect is lr.LaunchRecordDefect.ROW_NOT_BUILDABLE:
                    return False
                raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
            store.replace_ledger(completed, expected_digest=digest)
    except StoreError as error:
        if error.defect is StoreDefect.LEDGER_LOCKED:
            raise LaunchRefusalError("refused_ledger_locked", EXIT_REFUSED_LEDGER_LOCKED) from None
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
    return True


def _collection_payloads(records_dir: Path) -> list[bytes]:
    """Every collection record and disposition in the directory, as bytes."""
    paths = [
        *records_dir.glob("receipt-collection-*.json"),
        *records_dir.glob("collection-disposition-*.json"),
    ]
    return [path.read_bytes() for path in sorted(paths)]


def _dispositions_for(
    arguments: LaunchArguments, record: Any, *, receipt_lines: bytes, now: Callable[[], datetime]
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
            _collection_payloads(arguments.records_dir),
            identity=record.identity,
            launch_record_sha256=_launch_record_digest(record),
        )
    except CollectionRecordError as error:
        if error.defect is CollectionRecordDefect.RECEIPT_SUBSTITUTED:
            raise LaunchRefusalError(
                "refused_receipt_binding", EXIT_REFUSED_RECEIPT_BINDING
            ) from None
        raise LaunchRefusalError(
            "refused_collection_records", EXIT_REFUSED_COLLECTION_RECORDS
        ) from None
    except OSError:
        raise LaunchRefusalError(
            "refused_collection_records", EXIT_REFUSED_COLLECTION_RECORDS
        ) from None
    acknowledged = set(arguments.acknowledged_contradictions)
    known = set(status.unresolved) | set(status.disposed)
    if not set(status.unresolved) <= acknowledged or not acknowledged <= known:
        raise LaunchRefusalError(
            "refused_contradiction_unresolved", EXIT_REFUSED_CONTRADICTION_UNRESOLVED
        )
    try:
        line = collect_receipt_line(receipt_lines.decode("utf-8").splitlines())
    except (ReceiptError, UnicodeDecodeError):
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
    if not status.admits_line(line):
        # A disposition bound this launch to another receipt: no substitution.
        raise LaunchRefusalError("refused_receipt_binding", EXIT_REFUSED_RECEIPT_BINDING)
    if not status.unresolved:
        return []
    return [
        CollectionDisposition(
            identity=record.identity,
            launch_record_sha256=_launch_record_digest(record),
            contradiction_sha256=digest,
            receipt_line_sha256=sha256_hex(line.encode("utf-8")),
            disposition=ContradictionDisposition.HAND_READ_COMPLETION,
            recorded_at=now(),
        ).document()
        for digest in status.unresolved
    ]


def _launch_record_digest(record: Any) -> str:
    from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex

    return sha256_hex(canonical_bytes(record.document()))


def recover(
    arguments: LaunchArguments,
    *,
    now: Callable[[], datetime],
    root_source: Callable[[], Path] | None = None,
) -> None:
    """Record an interrupted attempt: the reserved identity receives its ledger row.

    The reservation proves the identity was consumed; whether a task ran, and to what
    end, the tool does not know -- the row is ``HALTED`` with ``EXIT_CODE_ONLY``
    evidence, and the owner reviews ECS by hand. Nothing is launched, and the
    reservation is kept: recovery makes the ledger agree with it, never the reverse.

    The reservation lives beside the ledger, so it is found whatever records directory
    the owner names. The row's slice and plan digest come from the reservation's own
    specification; a launch record for the identity in the named records directory
    refines the launch instant when it names the same specification, contradicts the
    reservation (and refuses) when it names another, and is simply absent -- an honest
    ``HALTED`` from the reservation alone -- when the owner named another directory.
    """
    from kalpamani.data.production.sharadar import launch_records as lr
    from kalpamani.data.production.sharadar.inputs import parse_slice
    from kalpamani.data.production.sharadar.launch_store import StoreDefect, StoreError
    from kalpamani.data.production.sharadar.vocabulary import ProductionActor

    store = _store(arguments, _private_root(root_source))
    try:
        with store.locked(now=now):
            ledger, digest = store.read_ledger()
            reservation = store.reservation(arguments.identity)
            if reservation is None or ledger.row(arguments.identity) is not None:
                raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS)
            if reservation.kind.value != arguments.kind or reservation.actor.value != (
                arguments.actor
            ):
                raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS)
            covered: Any = None
            plan_digest: str | None = None
            workload = reservation.specification.workload
            if reservation.actor is ProductionActor.ACQUISITION:
                covered = parse_slice(workload["slice"])
                plan_digest = workload["plan_digest"]
            launched_at = reservation.reserved_at
            # A launch record written before the interruption names what started; one
            # that names another specification is not this launch's and refuses.
            for path in store.launch_records():
                try:
                    candidate = lr.parse_launch_record(path.read_bytes())
                except (lr.LaunchRecordError, OSError):
                    continue
                if candidate.identity != arguments.identity:
                    continue
                if candidate.specification_digest != reservation.specification_digest:
                    raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS)
                launched_at = candidate.launched_at
            recorded_at = now()
            row = lr.OwnerLedgerRow(
                identity=arguments.identity,
                actor=reservation.actor,
                kind=reservation.kind,
                outcome="HALTED",
                evidence=lr.LedgerEvidence.EXIT_CODE_ONLY,
                launched_at=launched_at,
                completed_at=max(recorded_at, launched_at),
                slice=covered,
                plan_digest=plan_digest,
            )
            store.replace_ledger(lr.append_row(ledger, row), expected_digest=digest)
    except StoreError as error:
        if error.defect is StoreDefect.LEDGER_LOCKED:
            raise LaunchRefusalError("refused_ledger_locked", EXIT_REFUSED_LEDGER_LOCKED) from None
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
    except lr.LaunchRecordError:
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None


def record_isolation_verdict(
    arguments: LaunchArguments,
    *,
    now: Callable[[], datetime],
    root_source: Callable[[], Path] | None = None,
) -> Any:
    """Derive the R-2 verdict from the verified receipt and the owner's evidence; record it.

    The receipt must be a build verification receipt that verified against the launch
    record; the record must carry the verified placement and be bound to its
    reservation (:func:`_bound_reservation`) and to a ledger row; the evidence, when
    supplied, is parsed closed and bound by derivation (:func:`probe.isolation_verdict`).
    **The placement the verdict binds to is the recorded one** -- the interface, subnet
    and security groups the launcher verified and the reservation's specification
    named -- never a freshly supplied file's. The ``--launch-inputs`` argument is
    retained for the invocation's shape and is verified against the recorded
    specification: a file compiling to another placement or target refuses. The verdict
    document -- verdict, reason, components, whether the analysis bound, the
    specification digest -- is written into the records directory under an exclusive
    name. ``VERIFIED`` is unreachable without evidence, and this tool collects none.
    """
    from kalpamani.data.production.sharadar import launch_records as lr
    from kalpamani.data.production.sharadar import probe as pp
    from kalpamani.data.production.sharadar.entry import TaskEntry, TaskOutcome
    from kalpamani.data.production.sharadar.launch_store import StoreError

    store, record, verified = _record_and_receipt(arguments, root_source=root_source)
    if (
        record.entry is not TaskEntry.BUILD_VERIFY
        or verified.outcome is not TaskOutcome.VERIFIED_BOOTSTRAP
        or verified.probe is None
        or record.network_interface_id is None
        or record.subnet_id is None
        or record.security_group_ids is None
    ):
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS)
    reservation = _bound_reservation(store, record)
    try:
        ledger, _ = store.read_ledger()
    except StoreError:
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
    if ledger.row(record.identity) is None:
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS)
    # The launch-inputs file is checked against the recorded specification, never used.
    try:
        inputs = lr.parse_launch_inputs(_read(arguments.launch_inputs))
        compiled, target = lr.compile_launch(inputs, actor=record.actor, kind=record.kind)
    except lr.LaunchRecordError:
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
    specification = reservation.specification
    if compiled != specification.compiled or target != specification.target:
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS)
    evidence: Any = None
    if arguments.reachability_evidence is not None:
        try:
            evidence = pp.parse_reachability_evidence(_read(arguments.reachability_evidence))
        except ValueError:
            raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
    binding = pp.VerdictBinding(
        network_interface_id=record.network_interface_id,
        subnet_id=record.subnet_id,
        security_group_ids=frozenset(record.security_group_ids),
        launched_at=record.launched_at,
        recorded_at=record.recorded_at,
        binding_key=record.input_digest,
        origin_addresses=_origin_addresses(arguments, record),
    )
    result = pp.isolation_verdict(verified.probe, evidence, binding=binding)
    document = {
        "schema_version": lr.RECORD_SCHEMA_VERSION,
        "contract_id": pp.ISOLATION_VERDICT_CONTRACT_ID,
        "actor": record.actor.value,
        "kind": record.kind.value,
        "specification_digest": record.specification_digest,
        "probe": verified.probe.document(),
        "verdict": result.document(),
        "evidence_supplied": evidence is not None,
        "recorded_at": now().isoformat(),
    }
    try:
        store.write_record("isolation-verdict", document, at=now())
    except StoreError:
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
    return result


def _origin_addresses(arguments: LaunchArguments, record: Any) -> frozenset[str]:
    """The compiled origin set of the launched verification configuration.

    Read from the verification configuration file the owner supplies (the file the
    launch was prepared with), held to the record's registered digest so the set is
    the one the task carried and not a later edit.
    """
    from kalpamani.data.production.sharadar.compiled import (
        CompiledConfigurationError,
        parse_compiled_configuration,
    )

    assert arguments.verification_configuration is not None
    try:
        parsed, digest = parse_compiled_configuration(_read(arguments.verification_configuration))
    except CompiledConfigurationError:
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
    if digest != record.configuration_digest or parsed.origin_addresses is None:
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS)
    return frozenset(parsed.origin_addresses)


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


def _emit(lines: Sequence[str]) -> None:
    for line in lines:
        print(line)


def _environment(name: str) -> str | None:
    import os

    return os.environ.get(name)


def main(
    argv: Sequence[str] | None = None,
    *,
    clients: ClientFactory | None = None,
    environment: Callable[[str], str | None] | None = None,
    now: Callable[[], datetime] | None = None,
    monotonic: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
    root_source: Callable[[], Path] | None = None,
    security_of: Callable[[Path], Any] | None = None,
    while_running: Callable[[Any], None] | None = None,
) -> int:
    """Prepare offline; launch only with the flag and an authorization naming this specification.

    The keyword seams exist for tests, which inject fakes for every one of them. With
    none injected, the real clients are built **only** after the flag, the records, the
    authorization and the reservation are all admitted.
    """
    arguments_list = list(sys.argv[1:] if argv is None else argv)
    try:
        arguments = parse_arguments(arguments_list)
    except LaunchRefusalError as refusal:
        _emit([SENTENCES[refusal.key]])
        return refusal.exit_code

    clock = now if now is not None else (lambda: datetime.now(tz=UTC))
    try:
        if arguments.complete_row:
            receipt_text: str | None = None
            if arguments.collect_receipt:
                import time as _time

                # The real logs client exists only here, inside the collection flag, after
                # the record, the reservation, the registered destination and the launcher
                # identity are admitted (inside collect_receipt_lines).
                receipt_text = collect_receipt_lines(
                    arguments,
                    clients=clients if clients is not None else _Boto3Clients(),
                    environment=environment if environment is not None else _environment,
                    now=clock,
                    monotonic=monotonic if monotonic is not None else _time.monotonic,
                    sleep=sleep if sleep is not None else _time.sleep,
                    root_source=root_source,
                    security_of=security_of,
                )
            done = complete_row(
                arguments, now=clock, root_source=root_source, receipt_text=receipt_text
            )
            _emit([SENTENCES["row_completed" if done else "row_not_completed"]])
            return EXIT_ROW_COMPLETED if done else EXIT_ROW_NOT_COMPLETED
        if arguments.recover:
            recover(arguments, now=clock, root_source=root_source)
            _emit([SENTENCES["recovered"]])
            return EXIT_RECOVERED
        if arguments.isolation_verdict:
            result = record_isolation_verdict(arguments, now=clock, root_source=root_source)
            _emit(
                [
                    f"isolation_verdict={result.verdict.value} reason={result.reason.value}",
                    SENTENCES["verdict_recorded"],
                ]
            )
            return EXIT_VERDICT_RECORDED
        prepared = prepare_launch(arguments, now=clock(), root_source=root_source)
        if not arguments.authorized:
            write_specification(arguments, prepared, now=clock())
            _emit([*prepared.summary(), SENTENCES["prepared"]])
            return EXIT_PREPARED
        authorization_record = admit_authorization(arguments, prepared, now=clock())
        store = reserve_identity(arguments, prepared, now=clock, root_source=root_source)
    except LaunchRefusalError as refusal:
        _emit([SENTENCES[refusal.key]])
        return refusal.exit_code

    import time

    try:
        result = execute_launch(
            arguments,
            prepared,
            store=store,
            authorization_record=authorization_record,
            clients=clients if clients is not None else _Boto3Clients(),
            environment=environment if environment is not None else _environment,
            now=clock,
            monotonic=monotonic if monotonic is not None else time.monotonic,
            sleep=sleep if sleep is not None else time.sleep,
            root_source=root_source,
            security_of=security_of,
            while_running=while_running,
        )
    except LaunchRefusalError as refusal:
        _emit([SENTENCES[refusal.key]])
        return refusal.exit_code
    from kalpamani.data.production.sharadar.outcomes import LaunchOutcome, launch_sentence

    _emit(
        [
            launch_sentence(result.report.outcome),
            f"ledger_row={result.ledger_outcome} evidence={result.report.task_started}",
            SENTENCES["launched"],
        ]
    )
    return (
        EXIT_LAUNCH_TERMINAL
        if result.report.outcome is LaunchOutcome.TASK_TERMINAL
        else EXIT_LAUNCH_NOT_TERMINAL
    )


__all__ = [
    "AUTHORIZATION_FLAG",
    "REFUSED_FLAGS",
    "SENTENCES",
    "ClientFactory",
    "LaunchArguments",
    "LaunchRefusalError",
    "LaunchResult",
    "PreparedLaunch",
    "admit_authorization",
    "complete_row",
    "execute_launch",
    "main",
    "parse_arguments",
    "prepare_launch",
    "record_isolation_verdict",
    "recover",
    "reserve_identity",
    "workstation_client_config",
    "write_specification",
]


if __name__ == "__main__":  # pragma: no cover - the owner's console entry
    sys.exit(main())
