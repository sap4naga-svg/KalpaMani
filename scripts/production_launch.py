"""The owner-side launch tool (ADR-0036 §2.12; proposed ADR-0045). **Refuses by default.**

One authorized launch of one identity of one kind -- production or verification -- for one
actor, composing the accepted libraries and adding nothing to their contracts:

```text
records      the owner ledger, the launch-inputs record (Terraform outputs and image-gate
             values the owner transcribed), the owner's written authorization record, the
             slice (acquisition) or the run identities (build) -- each parsed closed by
             kalpamani.data.production.sharadar.launch_records
input        acquisition input v2 / build input v1, materialized with the accepted digest
             functions and re-parsed under the task's own contract before it leaves the tool
launch       CompiledLaunch from the records; human_bootstrap under the actor's human profile
             and again under its launcher profile; launch_authorized_run on real clients
             built ONLY inside the authorized branch; a launch record and a sanitized
             evidence document; one EXIT_CODE_ONLY ledger row
completion   --complete-row: the receipt line the owner read from the log stream, verified
             against the launch record, completes the row -- or refuses
```

**What the tool never does.** It never retries a ``RunTask`` (the adapter issues exactly
one; an ambiguous outcome is recorded as such and the identity stays consumed); it never
launches an identity the ledger already holds, for either kind; it never lets a
verification launch spend a production identity (the ``verify-`` prefix is reserved and
checked on every record); it never reads a receipt for the task (the owner hands it the
line); it never prints an ARN, an account id, a bucket, a key or an identity.

**An ordinary import does nothing observable**, and so does an invocation without the
authorization flag: the offline preparation runs, its sanitized summary is printed, and the
tool exits non-zero having constructed no client. Every SDK import sits inside the authorized
branch. **This tool has never run against AWS**: every test injects fakes.

Refused by name, so a wrong reflex fails loudly: ``--run``, ``--live``, ``--execute``,
``--force``, ``--retry``, ``--profile``, ``--aws-profile``, ``--skip-placement``,
``--no-cleanup``, ``--task-arn``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Protocol

#: The one flag that opens the authorized branch. Long on purpose.
AUTHORIZATION_FLAG: Final = "--i-am-the-owner-authorizing-one-launch"

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

#: Allowlisted output sentences. Nothing else reaches stdout.
SENTENCES: Final[dict[str, str]] = {
    "refused_arguments": "launch refused: the arguments were not admitted",
    "refused_records": "launch refused: an owner record was not admitted",
    "refused_authorization": "launch refused: no authorization for this launch",
    "refused_equivalence": "launch refused: the verification configuration is not equivalent",
    "refused_containment": "launch refused: the ledger and records must sit under the private root",
    "refused_dependency": "launch refused: a dependency could not be built",
    "refused_bootstrap": "launch refused: the human bootstrap did not prove an identity",
    "prepared": "launch prepared offline; no client was constructed and nothing was launched",
    "launched": "launch sequence finished; see the evidence document",
    "row_completed": "ledger row completed from the verified receipt",
    "row_not_completed": "ledger row not completed: the receipt establishes no disposition",
}

_ACTORS: Final = ("acquisition", "build")
_KINDS: Final = ("production", "verification")


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
    launch_record: Path | None
    receipt_lines: Path | None


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
    parser.add_argument("--launch-record", type=Path)
    parser.add_argument("--receipt-lines", type=Path)
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
        launch_record=namespace.launch_record,
        receipt_lines=namespace.receipt_lines,
    )
    if arguments.complete_row:
        if arguments.launch_record is None or arguments.receipt_lines is None:
            raise LaunchRefusalError("refused_arguments", EXIT_REFUSED_ARGUMENTS)
        if arguments.authorized:
            raise LaunchRefusalError("refused_arguments", EXIT_REFUSED_ARGUMENTS)
        return arguments
    acquisition = arguments.actor == "acquisition"
    if acquisition and (arguments.slice_path is None or arguments.run_identities):
        raise LaunchRefusalError("refused_arguments", EXIT_REFUSED_ARGUMENTS)
    if not acquisition and (arguments.slice_path is not None or not arguments.run_identities):
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
    authorization: Any
    ledger: Any
    slice: Any
    plan_digest: str | None
    equivalence: str | None

    def __repr__(self) -> str:
        """A fixed token."""
        return "PreparedLaunch(<private>)"

    def summary(self) -> tuple[str, ...]:
        """Sanitized lines: actor, kind, entry, input bytes, equivalence verdict."""
        lines = [
            f"actor={self.actor.value} kind={self.kind.value} entry={self.entry.value}",
            f"input_bytes={len(self.authorization.input_bytes)} "
            f"ledger_rows={len(self.ledger.rows)}",
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


def prepare_launch(
    arguments: LaunchArguments,
    *,
    now: datetime,
    root_source: Callable[[], Path] | None = None,
) -> PreparedLaunch:
    """Parse every record, materialize the input, compile the launch. **Offline.**

    Raises :class:`LaunchRefusalError` with a closed key; never a value.
    """
    from kalpamani.data.production.sharadar import launch_records as lr
    from kalpamani.data.production.sharadar.entry import TaskEntry
    from kalpamani.data.production.sharadar.launcher import LaunchAuthorization
    from kalpamani.data.production.sharadar.vocabulary import ProductionActor
    from kalpamani.data.qualify.sharadar.runtime_binding import private_root

    actor = ProductionActor(arguments.actor)
    kind = lr.LaunchKind(arguments.kind)
    entry = {
        (ProductionActor.ACQUISITION, lr.LaunchKind.PRODUCTION): TaskEntry.ACQUISITION,
        (ProductionActor.ACQUISITION, lr.LaunchKind.VERIFICATION): TaskEntry.ACQUISITION_VERIFY,
        (ProductionActor.BUILD, lr.LaunchKind.PRODUCTION): TaskEntry.BUILD,
        (ProductionActor.BUILD, lr.LaunchKind.VERIFICATION): TaskEntry.BUILD_VERIFY,
    }[(actor, kind)]

    # Containment: the ledger and the records directory sit under the private root, so an
    # identity, a slice or an ARN can never be written into a tracked tree by this tool.
    try:
        root = (private_root if root_source is None else root_source)()
    except Exception:
        raise LaunchRefusalError("refused_containment", EXIT_REFUSED_CONTAINMENT) from None
    if not _contained(arguments.ledger, root) or not _contained(arguments.records_dir, root):
        raise LaunchRefusalError("refused_containment", EXIT_REFUSED_CONTAINMENT)

    try:
        ledger = lr.parse_owner_ledger(_read(arguments.ledger))
        inputs = lr.parse_launch_inputs(_read(arguments.launch_inputs))
        covered: Any = None
        plan_digest: str | None = None
        if actor is ProductionActor.ACQUISITION:
            assert arguments.slice_path is not None
            from kalpamani.data.production.sharadar.documents import decode_document

            slice_document = decode_document(
                _read(arguments.slice_path), max_bytes=lr.MAX_RECORD_BYTES
            )
            input_bytes = lr.materialize_acquisition_input(
                ledger,
                identity=arguments.identity,
                kind=kind,
                slice_document=slice_document,
                now=now,
            )
            from kalpamani.data.contracts.vocabulary import AcquisitionMode
            from kalpamani.data.production.sharadar.inputs import parse_slice
            from kalpamani.data.production.sharadar.plan import plan_digest_for

            covered = parse_slice(slice_document)
            plan_digest = plan_digest_for(
                covered, acquisition_mode=AcquisitionMode(covered.acquisition_mode)
            )
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
        production = _read(arguments.production_configuration)
        verification = _read(arguments.verification_configuration)
        acquisition = (
            None
            if arguments.acquisition_configuration is None
            else _read(arguments.acquisition_configuration)
        )
        verdict = lr.configuration_equivalence(
            production=production, verification=verification, acquisition=acquisition
        )
        equivalence = verdict.value
        if verdict is not lr.EquivalenceVerdict.EQUIVALENT:
            raise LaunchRefusalError("refused_equivalence", EXIT_REFUSED_EQUIVALENCE)
        # The verification file the image carries is the one the launch-inputs record
        # registered: its digest and commit must be the target's, or the equivalence
        # was checked against the wrong file.
        from kalpamani.data.production.sharadar.compiled import parse_compiled_configuration

        parsed, digest = parse_compiled_configuration(verification)
        if (
            digest != target.configuration_digest
            or parsed.compiled.code_commit != target.code_commit
            or parsed.entry is not entry
        ):
            raise LaunchRefusalError("refused_equivalence", EXIT_REFUSED_EQUIVALENCE)

    authorization = LaunchAuthorization(identity=arguments.identity, input_bytes=input_bytes)
    return PreparedLaunch(
        actor=actor,
        kind=kind,
        entry=entry,
        compiled=compiled,
        target=target,
        authorization=authorization,
        ledger=ledger,
        slice=covered,
        plan_digest=plan_digest,
        equivalence=equivalence,
    )


def admit_authorization(
    arguments: LaunchArguments, prepared: PreparedLaunch, *, now: datetime
) -> None:
    """The owner's written authorization for THIS actor, kind and identity, or refuse."""
    from kalpamani.data.production.sharadar import launch_records as lr

    if arguments.authorization is None:
        raise LaunchRefusalError("refused_authorization", EXIT_REFUSED_AUTHORIZATION)
    try:
        lr.parse_authorization(
            _read(arguments.authorization),
            actor=prepared.actor,
            kind=prepared.kind,
            identity=arguments.identity,
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


def workstation_client_config() -> dict[str, object]:
    """The botocore ``Config`` arguments for every workstation client. Pure.

    The same finite socket timeouts and **one attempt in total** as a task's SSM and STS
    clients: a hidden SDK retry of ``RunTask`` would be a second launch, of a parameter
    write a second create, of ``DescribeTasks`` an observation the ceiling never counted.
    """
    from kalpamani.data.production.sharadar.task_clients import TaskService, client_config_kwargs

    return client_config_kwargs(TaskService.SSM)


class _Boto3Clients:
    """Real clients from ``boto3.Session(profile_name=...)``. Constructed only when authorized."""

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


def execute_launch(
    arguments: LaunchArguments,
    prepared: PreparedLaunch,
    *,
    clients: ClientFactory,
    environment: Callable[[str], str | None],
    now: Callable[[], datetime],
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
    root_source: Callable[[], Path] | None = None,
    security_of: Callable[[Path], Any] | None = None,
) -> LaunchResult:
    """The authorized branch: two bootstraps, one launch, the records, one ledger row.

    The human bootstrap runs under the actor's human profile and again under its
    launcher profile, each proving its own identity against the same private binding
    file before any parameter or ECS call; the launcher's before-and-after proofs then
    call STS under the profile the path names. A bootstrap that refuses stops the tool
    before any adapter exists.
    """
    from kalpamani.data.production.sharadar import launch_records as lr
    from kalpamani.data.production.sharadar.compute import Ec2InterfaceAdapter, EcsTaskAdapter
    from kalpamani.data.production.sharadar.identity import (
        ProvenIdentity,
        production_identity_refusal,
    )
    from kalpamani.data.production.sharadar.inputs import input_digest
    from kalpamani.data.production.sharadar.launcher import LaunchAdapters, launch_authorized_run
    from kalpamani.data.production.sharadar.outcomes import LaunchOutcome
    from kalpamani.data.production.sharadar.parameters import SsmParameterAdapter
    from kalpamani.data.production.sharadar.runner import HumanBootstrapOutcome, human_bootstrap
    from kalpamani.data.production.sharadar.vocabulary import IdentityPath, constants_for

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

    launched_at = now()
    report = launch_authorized_run(
        compiled=prepared.compiled,
        adapters=adapters,
        authorization=prepared.authorization,
        identity_proof=identity_proof,
        now=now,
        monotonic=monotonic,
        sleep=sleep,
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
    ledger = lr.append_row(prepared.ledger, row)

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
    # The ledger is rewritten last, after the records exist: a tool that died between the
    # two would leave the identity unrecorded in the ledger but recorded in the records
    # directory, and the owner reconciles from there. The ledger is never left half-written.
    stamp = recorded_at.strftime("%Y%m%dT%H%M%SZ")
    evidence_path = arguments.records_dir / f"launch-evidence-{stamp}.json"
    record_path = None if record is None else arguments.records_dir / f"launch-record-{stamp}.json"
    from kalpamani.data.contracts.canonical import canonical_bytes

    arguments.records_dir.mkdir(parents=True, exist_ok=True)
    evidence_path.write_bytes(canonical_bytes(evidence))
    if record is not None and record_path is not None:
        record_path.write_bytes(canonical_bytes(record.document()))
    arguments.ledger.write_bytes(canonical_bytes(ledger.document()))
    return LaunchResult(
        report=report, ledger_outcome=outcome, evidence_path=evidence_path, record_path=record_path
    )


# ---------------------------------------------------------------------------
# Row completion
# ---------------------------------------------------------------------------


def complete_row(
    arguments: LaunchArguments, *, root_source: Callable[[], Path] | None = None
) -> bool:
    """Verify the hand-read receipt against the launch record and complete the row.

    Returns ``True`` when the row was completed and the ledger rewritten, ``False`` when
    the verified receipt establishes no disposition (the row stays provisional). A
    receipt that does not belong to the record refuses as a record refusal.
    """
    from kalpamani.data.production.sharadar import launch_records as lr
    from kalpamani.data.production.sharadar.receipts import ReceiptError, collect_and_verify
    from kalpamani.data.qualify.sharadar.runtime_binding import private_root

    assert arguments.launch_record is not None and arguments.receipt_lines is not None
    try:
        root = (private_root if root_source is None else root_source)()
    except Exception:
        raise LaunchRefusalError("refused_containment", EXIT_REFUSED_CONTAINMENT) from None
    if not _contained(arguments.ledger, root) or not _contained(arguments.launch_record, root):
        raise LaunchRefusalError("refused_containment", EXIT_REFUSED_CONTAINMENT)
    try:
        ledger = lr.parse_owner_ledger(_read(arguments.ledger))
        record = lr.parse_launch_record(_read(arguments.launch_record))
    except lr.LaunchRecordError:
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
    if record.identity != arguments.identity or record.kind.value != arguments.kind:
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS)
    if record.actor.value != arguments.actor:
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS)
    try:
        text = _read(arguments.receipt_lines).decode("utf-8")
    except UnicodeDecodeError:
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
    try:
        verified = collect_and_verify(text.splitlines(), expectation=record.expectation())
    except ReceiptError:
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
    existing = ledger.row(record.identity)
    if existing is None or existing.evidence is not lr.LedgerEvidence.EXIT_CODE_ONLY:
        # No provisional row to complete: never launched by this ledger, or completed already.
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS)
    try:
        completed = lr.complete_ledger_row(ledger, record=record, receipt=verified)
    except lr.LaunchRecordError as error:
        if error.defect is lr.LaunchRecordDefect.ROW_NOT_BUILDABLE:
            # The receipt is this launch's and establishes no disposition: owner review.
            return False
        raise LaunchRefusalError("refused_records", EXIT_REFUSED_RECORDS) from None
    from kalpamani.data.contracts.canonical import canonical_bytes

    arguments.ledger.write_bytes(canonical_bytes(completed.document()))
    return True


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
) -> int:
    """Prepare offline; launch only with the flag and a matching authorization record.

    The keyword seams exist for tests, which inject fakes for every one of them. With
    none injected, the real clients are built **only** after the flag, the records and
    the authorization are all admitted.
    """
    arguments_list = list(sys.argv[1:] if argv is None else argv)
    try:
        arguments = parse_arguments(arguments_list)
    except LaunchRefusalError as refusal:
        _emit([SENTENCES[refusal.key]])
        return refusal.exit_code

    if arguments.complete_row:
        try:
            done = complete_row(arguments, root_source=root_source)
        except LaunchRefusalError as refusal:
            _emit([SENTENCES[refusal.key]])
            return refusal.exit_code
        _emit([SENTENCES["row_completed" if done else "row_not_completed"]])
        return EXIT_ROW_COMPLETED if done else EXIT_ROW_NOT_COMPLETED

    clock = now if now is not None else (lambda: datetime.now(tz=UTC))
    try:
        prepared = prepare_launch(arguments, now=clock(), root_source=root_source)
        if not arguments.authorized:
            _emit([*prepared.summary(), SENTENCES["prepared"]])
            return EXIT_PREPARED
        admit_authorization(arguments, prepared, now=clock())
    except LaunchRefusalError as refusal:
        _emit([SENTENCES[refusal.key]])
        return refusal.exit_code

    import time

    try:
        result = execute_launch(
            arguments,
            prepared,
            clients=clients if clients is not None else _Boto3Clients(),
            environment=environment if environment is not None else _environment,
            now=clock,
            monotonic=monotonic if monotonic is not None else time.monotonic,
            sleep=sleep if sleep is not None else time.sleep,
            root_source=root_source,
            security_of=security_of,
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
    "workstation_client_config",
]


if __name__ == "__main__":  # pragma: no cover - the owner's console entry
    sys.exit(main())
