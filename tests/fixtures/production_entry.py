"""Synthetic harnesses for the production task entries. **Nothing here is real.**

Two harnesses drive the real entry functions -- :func:`run_task_entry` and the actor
entries beneath it -- with injected fakes for every factory: an SSM-shaped store, an
STS-shaped identity, a get-and-put S3 store, a secrets fake, the coordinate-answering
scripted transport, a canned metadata document and a canned origin resolver. Every
address, ARN, account, identifier and identity is invented. **Mocked results are not
AWS or provider verification.**
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final

from fixtures.production_build import (
    BUILD_NOW,
    RUN_1,
    RUN_1_AT,
    RUN_2,
    RUN_2_AT,
    SECRET_ID,
    FakeS3Store,
    FakeSecrets,
    ShiftedClock,
    configuration,
    ledger_row,
    responses_for_run,
    slice_for_run,
)
from fixtures.production_provider import CoordinateTransport
from fixtures.production_runtime import (
    ACCOUNT,
    BUILD_ID,
    CONFIGURATION_DIGEST,
    IMAGE_DIGEST,
    INTERFACE_ID,
    SUBNET_ID,
    TASK_ARN,
    FakeClientError,
    FakeSsm,
    binding_document,
    build_input_document,
    compiled_task,
    compiled_verification_task,
    encode,
    metadata_document,
    revision_arn,
    task_identity_arn,
    verification_revision_arn,
)
from kalpamani.data.contracts.vocabulary import AcquisitionMode
from kalpamani.data.production.sharadar.acquisition_entry import AcquisitionFactories
from kalpamani.data.production.sharadar.build_entry import BuildFactories
from kalpamani.data.production.sharadar.entry import (
    EntryConfiguration,
    TaskEntry,
    TaskReceipt,
    run_task_entry,
)
from kalpamani.data.production.sharadar.identities import SpentIdentityRegistry
from kalpamani.data.production.sharadar.inputs import (
    ACQUISITION_INPUT_SCHEMA_VERSION,
    input_digest,
    ledger_digest,
    parse_slice,
    spent_identities_block,
)
from kalpamani.data.production.sharadar.metadata import METADATA_URI_ENV_VAR
from kalpamani.data.production.sharadar.permission_cells import (
    PRINCIPAL_ACTOR,
    Operation,
    PermissionContext,
    PermissionTargets,
    Subcell,
    subcell,
)
from kalpamani.data.production.sharadar.permission_probe import (
    PermissionProbeInput,
    probe_identity,
)
from kalpamani.data.production.sharadar.permission_probe_entry import PermissionProbeFactories
from kalpamani.data.production.sharadar.plan import plan_digest_for
from kalpamani.data.production.sharadar.probe import ProbeResult
from kalpamani.data.production.sharadar.release import build_release_document
from kalpamani.data.production.sharadar.verification_entry import VerificationFactories
from kalpamani.data.production.sharadar.vocabulary import ProductionActor, constants_for

ACQ: Final = ProductionActor.ACQUISITION
BUILD: Final = ProductionActor.BUILD

#: A task's environment, by name only. The container credential provider is present.
TASK_ENVIRONMENT_NAMES: Final[tuple[str, ...]] = (
    "PATH",
    "HOSTNAME",
    METADATA_URI_ENV_VAR,
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
    "AWS_REGION",
)
METADATA_URI: Final = "http://169.254.170.2/v4/0123456789abcdef0123456789abcdef-0"
#: The Fargate container credential relative URI, as the agent places it (synthetic id).
CONTAINER_URI: Final = "/v2/credentials/00000000-0000-4000-8000-000000000000"
#: Documentation-range addresses (RFC 5737); they route nowhere.
ORIGIN_ADDRESSES: Final[frozenset[str]] = frozenset({"192.0.2.10", "192.0.2.11"})


def resolve_inside(host: str) -> list[str]:
    return sorted(ORIGIN_ADDRESSES)


def resolve_outside(host: str) -> list[str]:
    return ["192.0.2.10", "198.51.100.7"]


class FakeSts:
    """An STS-shaped fake answering one assumed-role identity, or failing."""

    def __init__(self, arn: str, *, account: str = ACCOUNT, failure: str | None = None) -> None:
        self.arn = arn
        self.account = account
        self.failure = failure
        self.calls = 0

    def get_caller_identity(self) -> dict[str, str]:
        self.calls += 1
        if self.failure is not None:
            raise FakeClientError(self.failure)
        return {"UserId": "AROASYNTHETIC:0123", "Account": self.account, "Arn": self.arn}


@dataclass
class MetadataSource:
    """A canned task metadata v4 document behind the fetch shape; records every call."""

    document: dict[str, Any] | None
    raw: bytes | None = None
    failure: Exception | None = None
    calls: list[tuple[str, float, int]] = field(default_factory=list)

    def fetch(self, url: str, timeout_seconds: float, max_bytes: int) -> bytes:
        self.calls.append((url, timeout_seconds, max_bytes))
        if self.failure is not None:
            raise self.failure
        if self.raw is not None:
            return self.raw
        assert self.document is not None
        return encode(self.document)


class Constructions:
    """Counts what each factory was asked to build, so a refusal can prove zero."""

    def __init__(self) -> None:
        self.built: list[str] = []

    def factory(self, name: str, value: Any) -> Callable[[], Any]:
        def build() -> Any:
            self.built.append(name)
            if isinstance(value, Exception):
                raise value
            return value

        return build


class AcquisitionHarness:
    """One acquisition task through the real entry, every dependency injected."""

    def __init__(
        self,
        *,
        store: FakeS3Store | None = None,
        run_id: str = RUN_1,
        run: int = 1,
        at: datetime = RUN_1_AT,
        responses: dict[tuple[str, str, int], bytes] | None = None,
        slice_doc: dict[str, Any] | None = None,
        release: bool = True,
        spent: SpentIdentityRegistry | None = None,
        spent_before: tuple[str, ...] = (),
    ) -> None:
        constants = constants_for(ACQ)
        self.run_id = run_id
        slice_doc = slice_for_run(run) if slice_doc is None else slice_doc
        digest = plan_digest_for(parse_slice(slice_doc), acquisition_mode=AcquisitionMode.BACKFILL)
        self.input_bytes = encode(
            {
                "schema_version": ACQUISITION_INPUT_SCHEMA_VERSION,
                "contract_id": constants.input_contract_id,
                "run_identity": run_id,
                "slice": slice_doc,
                "plan_digest": digest,
                "spent_identities": spent_identities_block(list(spent_before)),
                "issued_at": (at - timedelta(hours=1)).isoformat(),
                "expires_at": (at + timedelta(hours=23)).isoformat(),
            }
        )
        self.ssm = FakeSsm()
        self.ssm.values[constants.binding_parameter] = encode(binding_document(ACQ))
        self.ssm.values[constants.input_parameter] = self.input_bytes
        if release:
            self.ssm.values[constants.release_parameter] = build_release_document(
                actor=ACQ,
                task_arn=TASK_ARN,
                task_definition_arn=revision_arn(ACQ),
                image_digest=IMAGE_DIGEST,
                configuration_digest=CONFIGURATION_DIGEST,
                identity=run_id,
                input_digest=input_digest(self.input_bytes),
                network_interface_id=INTERFACE_ID,
                subnet_id=SUBNET_ID,
                verified_at=at - timedelta(seconds=10),
            )
        self.clock = ShiftedClock(base=at)
        self.store = FakeS3Store() if store is None else store
        self._puts_before = len(self.store.puts)
        self.secrets = FakeSecrets()
        self.sts = FakeSts(task_identity_arn(ACQ))
        self.transport = CoordinateTransport(
            responses=responses_for_run(run, slice_doc) if responses is None else responses
        )
        self.metadata = MetadataSource(metadata_document(ACQ))
        self.spent = spent
        self.constructions = Constructions()
        self.cleanups = 0
        self.environment_names: tuple[str, ...] = TASK_ENVIRONMENT_NAMES
        self.environment: dict[str, str] = {
            METADATA_URI_ENV_VAR: METADATA_URI,
            "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI": CONTAINER_URI,
        }
        self.resolve: Callable[[str], Iterable[object]] = resolve_inside

    def cleanup(self) -> None:
        self.cleanups += 1

    def configuration(self, **overrides: Any) -> EntryConfiguration:
        fields_: dict[str, Any] = {
            "entry": TaskEntry.ACQUISITION,
            "compiled": compiled_task(ACQ),
            "secret_identifier": SECRET_ID,
            "origin_addresses": ORIGIN_ADDRESSES,
        }
        fields_.update(overrides)
        return EntryConfiguration(**fields_)

    def factories(self, **overrides: Any) -> AcquisitionFactories:
        build = self.constructions.factory
        fields_: dict[str, Any] = {
            "environment_names": lambda: list(self.environment_names),
            "environment": self.environment.get,
            "metadata_fetch": self.metadata.fetch,
            "ssm": build("ssm", self.ssm),
            "sts": build("sts", self.sts),
            "s3": build("s3", self.store),
            "secrets": build("secrets", self.secrets),
            "transport": build("transport", self.transport),
            "resolve_origin": self.resolve,
            "spent_identities": self.spent,
            "now": self.clock.now,
            "monotonic": self.clock.monotonic,
            "sleep": self.clock.sleep,
            "cleanup": self.cleanup,
        }
        fields_.update(overrides)
        return AcquisitionFactories(**fields_)

    def run(
        self, configuration: EntryConfiguration | None = None, **factory_overrides: Any
    ) -> TaskReceipt:
        return run_task_entry(
            entry=TaskEntry.ACQUISITION,
            configuration=self.configuration() if configuration is None else configuration,
            factories=self.factories(**factory_overrides),
        )

    def data_plane_calls(self) -> tuple[int, int, int]:
        """(secret retrievals, transport invocations, S3 puts) since this harness began."""
        return (
            self.secrets.calls,
            self.transport.call_count,
            len(self.store.puts) - self._puts_before,
        )


class BuildHarness:
    """One build task through the real entry over a populated store."""

    def __init__(
        self,
        store: FakeS3Store,
        *,
        runs: tuple[tuple[str, int, datetime], ...] = ((RUN_1, 1, RUN_1_AT), (RUN_2, 2, RUN_2_AT)),
        now: datetime = BUILD_NOW,
        release: bool = True,
        slices: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        constants = constants_for(BUILD)
        rows = [ledger_row(run_id, run, at, (slices or {}).get(run_id)) for run_id, run, at in runs]
        self.ssm = FakeSsm()
        self.ssm.values[constants.binding_parameter] = encode(binding_document(BUILD))
        self.input_bytes = encode(
            build_input_document(
                rows,
                build_identity=BUILD_ID,
                ledger_digest=ledger_digest(rows),
                issued_at=(now - timedelta(hours=1)).isoformat(),
                expires_at=(now + timedelta(hours=23)).isoformat(),
            )
        )
        self.ssm.values[constants.input_parameter] = self.input_bytes
        if release:
            self.ssm.values[constants.release_parameter] = build_release_document(
                actor=BUILD,
                task_arn=TASK_ARN,
                task_definition_arn=revision_arn(BUILD),
                image_digest=IMAGE_DIGEST,
                configuration_digest=CONFIGURATION_DIGEST,
                identity=BUILD_ID,
                input_digest=input_digest(self.input_bytes),
                network_interface_id=INTERFACE_ID,
                subnet_id=SUBNET_ID,
                verified_at=now - timedelta(seconds=10),
            )
        self.clock = ShiftedClock(base=now)
        self.store = store
        self._gets_before = len(store.gets)
        self._puts_before = len(store.puts)
        self.sts = FakeSts(task_identity_arn(BUILD))
        self.metadata = MetadataSource(metadata_document(BUILD))
        self.constructions = Constructions()
        self.cleanups = 0
        self.environment_names: tuple[str, ...] = TASK_ENVIRONMENT_NAMES
        self.environment: dict[str, str] = {
            METADATA_URI_ENV_VAR: METADATA_URI,
            "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI": CONTAINER_URI,
        }

    def cleanup(self) -> None:
        self.cleanups += 1

    def configuration(self, **overrides: Any) -> EntryConfiguration:
        fields_: dict[str, Any] = {
            "entry": TaskEntry.BUILD,
            "compiled": compiled_task(BUILD),
            "build_configuration": configuration(),
        }
        fields_.update(overrides)
        return EntryConfiguration(**fields_)

    def factories(self, **overrides: Any) -> BuildFactories:
        build = self.constructions.factory
        fields_: dict[str, Any] = {
            "environment_names": lambda: list(self.environment_names),
            "environment": self.environment.get,
            "metadata_fetch": self.metadata.fetch,
            "ssm": build("ssm", self.ssm),
            "sts": build("sts", self.sts),
            "s3": build("s3", self.store),
            "now": self.clock.now,
            "monotonic": self.clock.monotonic,
            "sleep": self.clock.sleep,
            "cleanup": self.cleanup,
        }
        fields_.update(overrides)
        return BuildFactories(**fields_)

    def run(
        self, configuration: EntryConfiguration | None = None, **factory_overrides: Any
    ) -> TaskReceipt:
        return run_task_entry(
            entry=TaskEntry.BUILD,
            configuration=self.configuration() if configuration is None else configuration,
            factories=self.factories(**factory_overrides),
        )

    def data_plane_calls(self) -> tuple[int, int]:
        """(gets, puts) this build asked the store for."""
        return (len(self.store.gets) - self._gets_before, len(self.store.puts) - self._puts_before)


class FakeProbe:
    """A probe adapter answering one canned result (or raising); records every attempt."""

    def __init__(self, result: ProbeResult | Exception = ProbeResult.TIMED_OUT) -> None:
        self.result = result
        self.attempts: list[tuple[str, int, float]] = []

    def connect(self, address: str, port: int, timeout_seconds: float) -> ProbeResult:
        self.attempts.append((address, port, timeout_seconds))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class VerificationHarness:
    """One verification task (proposed ADR-0045) through the real entry, every dependency injected.

    The binding, input and release are the actor's real contracts; the metadata reports
    the VERIFICATION family and the release names the verification revision. There is
    no store, no secrets fake and no transport: the factories have no field for them.
    """

    def __init__(
        self,
        *,
        entry: TaskEntry,
        at: datetime = RUN_1_AT,
        release: bool = True,
        probe: FakeProbe | None = None,
    ) -> None:
        if entry not in (TaskEntry.ACQUISITION_VERIFY, TaskEntry.BUILD_VERIFY):
            raise ValueError("a verification harness runs a verification entry")
        self.entry = entry
        actor = ACQ if entry is TaskEntry.ACQUISITION_VERIFY else BUILD
        self.actor = actor
        constants = constants_for(actor)
        if actor is ACQ:
            slice_doc = slice_for_run(1)
            digest = plan_digest_for(
                parse_slice(slice_doc), acquisition_mode=AcquisitionMode.BACKFILL
            )
            self.identity = "verify-" + RUN_1
            self.input_bytes = encode(
                {
                    "schema_version": ACQUISITION_INPUT_SCHEMA_VERSION,
                    "contract_id": constants.input_contract_id,
                    "run_identity": self.identity,
                    "slice": slice_doc,
                    "plan_digest": digest,
                    "spent_identities": spent_identities_block([]),
                    "issued_at": (at - timedelta(hours=1)).isoformat(),
                    "expires_at": (at + timedelta(hours=23)).isoformat(),
                }
            )
        else:
            rows = [ledger_row(RUN_1, 1, RUN_1_AT, None)]
            self.identity = "verify-" + BUILD_ID
            self.input_bytes = encode(
                build_input_document(
                    rows,
                    build_identity=self.identity,
                    ledger_digest=ledger_digest(rows),
                    issued_at=(at - timedelta(hours=1)).isoformat(),
                    expires_at=(at + timedelta(hours=23)).isoformat(),
                )
            )
        self.ssm = FakeSsm()
        self.ssm.values[constants.binding_parameter] = encode(binding_document(actor))
        self.ssm.values[constants.input_parameter] = self.input_bytes
        if release:
            self.ssm.values[constants.release_parameter] = build_release_document(
                actor=actor,
                task_arn=TASK_ARN,
                task_definition_arn=verification_revision_arn(actor),
                image_digest=IMAGE_DIGEST,
                configuration_digest=CONFIGURATION_DIGEST,
                identity=self.identity,
                input_digest=input_digest(self.input_bytes),
                network_interface_id=INTERFACE_ID,
                subnet_id=SUBNET_ID,
                verified_at=at - timedelta(seconds=10),
            )
        self.clock = ShiftedClock(base=at)
        self.sts = FakeSts(task_identity_arn(actor))
        self.metadata = MetadataSource(
            metadata_document(actor, Family=constants.verification_task_family)
        )
        self.probe = probe if probe is not None else FakeProbe()
        self.constructions = Constructions()
        self.cleanups = 0
        self.environment_names: tuple[str, ...] = TASK_ENVIRONMENT_NAMES
        self.environment: dict[str, str] = {
            METADATA_URI_ENV_VAR: METADATA_URI,
            "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI": CONTAINER_URI,
        }
        self.resolve: Callable[[str], Iterable[object]] = resolve_inside

    def cleanup(self) -> None:
        self.cleanups += 1

    def configuration(self, **overrides: Any) -> EntryConfiguration:
        fields_: dict[str, Any] = {
            "entry": self.entry,
            "compiled": compiled_verification_task(self.actor),
            "origin_addresses": ORIGIN_ADDRESSES,
        }
        fields_.update(overrides)
        return EntryConfiguration(**fields_)

    def factories(self, **overrides: Any) -> VerificationFactories:
        build = self.constructions.factory
        fields_: dict[str, Any] = {
            "environment_names": lambda: list(self.environment_names),
            "environment": self.environment.get,
            "metadata_fetch": self.metadata.fetch,
            "ssm": build("ssm", self.ssm),
            "sts": build("sts", self.sts),
            "resolve_origin": self.resolve,
            "probe": self.probe if self.entry is TaskEntry.BUILD_VERIFY else None,
            "now": self.clock.now,
            "monotonic": self.clock.monotonic,
            "sleep": self.clock.sleep,
            "cleanup": self.cleanup,
        }
        fields_.update(overrides)
        return VerificationFactories(**fields_)

    def run(
        self, configuration: EntryConfiguration | None = None, **factory_overrides: Any
    ) -> TaskReceipt:
        return run_task_entry(
            entry=self.entry,
            configuration=self.configuration() if configuration is None else configuration,
            factories=self.factories(**factory_overrides),
        )


class FakeOperationClient:
    """A permission-client-shaped fake for the probe task: one scripted answer per call.

    Every operation records its name and arguments; the answers are handed out in
    order. An exception scripted as an answer is raised.
    """

    def __init__(self, answers: list[Any] | None = None) -> None:
        self.answers = list(answers or [])
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _answer(self, name: str, **kwargs: Any) -> Any:
        self.calls.append((name, kwargs))
        if not self.answers:
            raise AssertionError(f"no answer scripted for {name}")
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        def call(*args: Any, **kwargs: Any) -> Any:
            return self._answer(name, args=args, **kwargs)

        return call


class ProbeHarness:
    """One permission-probe task (proposed ADR-0048) through the real entry, injected.

    The binding and release are the actor's real contracts; the input is the probe input
    naming ``subcell_id`` and its resolved target under ``context``; the metadata reports
    the PROBE family and the release names the probe revision. The one operation client
    is a scripted fake handed to the entry's ``operation_client`` factory.
    """

    def __init__(
        self,
        *,
        subcell_id: str,
        context: PermissionContext,
        at: datetime = RUN_1_AT,
        release: bool = True,
        hold_seconds: int = 0,
        stamp: str = "20260912T140000Z-abcd",
        statement_sha256: str = "a1" * 32,
        attempt_sha256: str = "b2" * 32,
        target_overrides: dict[str, Any] | None = None,
        input_overrides: dict[str, Any] | None = None,
    ) -> None:
        from fixtures.production_runtime import compiled_probe_task, probe_revision_arn

        cell: Subcell = subcell(subcell_id)
        actor = PRINCIPAL_ACTOR[cell.principal]
        assert actor is not None
        self.cell = cell
        self.actor = actor
        self.entry = TaskEntry.ACQUISITION_PROBE if actor is ACQ else TaskEntry.BUILD_PROBE
        constants = constants_for(actor)
        self.stamp = stamp
        self.identity = probe_identity(stamp)
        target = context.resolve(cell, stamp=stamp, prerequisites={}).document()
        target.update(target_overrides or {})
        self.probe_input = PermissionProbeInput(
            actor=actor,
            identity=self.identity,
            subcell_id=subcell_id,
            statement_sha256=statement_sha256,
            attempt_sha256=attempt_sha256,
            stamp=stamp,
            target=target,
            hold_seconds=hold_seconds,
            issued_at=at - timedelta(hours=1),
            expires_at=at + timedelta(hours=23),
        )
        document = self.probe_input.document()
        document.update(input_overrides or {})
        self.input_bytes = encode(document)
        self.ssm = FakeSsm()
        self.ssm.values[constants.binding_parameter] = encode(binding_document(actor))
        self.ssm.values[constants.input_parameter] = self.input_bytes
        if release:
            self.ssm.values[constants.release_parameter] = build_release_document(
                actor=actor,
                task_arn=TASK_ARN,
                task_definition_arn=probe_revision_arn(actor),
                image_digest=IMAGE_DIGEST,
                configuration_digest=CONFIGURATION_DIGEST,
                identity=self.identity,
                input_digest=input_digest(self.input_bytes),
                network_interface_id=INTERFACE_ID,
                subnet_id=SUBNET_ID,
                verified_at=at - timedelta(seconds=10),
            )
        self.clock = ShiftedClock(base=at)
        self.sts = FakeSts(task_identity_arn(actor))
        self.metadata = MetadataSource(metadata_document(actor, Family=constants.probe_task_family))
        self.constructions = Constructions()
        self.operation = FakeOperationClient()
        self.services: list[Operation] = []
        self.compiled = compiled_probe_task(actor)
        self.cleanups = 0
        self.environment_names: tuple[str, ...] = TASK_ENVIRONMENT_NAMES
        self.environment: dict[str, str] = {
            METADATA_URI_ENV_VAR: METADATA_URI,
            "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI": CONTAINER_URI,
        }

    def cleanup(self) -> None:
        self.cleanups += 1

    def operation_client(self, operation: Operation) -> Any:
        self.services.append(operation)
        return self.operation

    def configuration(self, **overrides: Any) -> EntryConfiguration:
        fields_: dict[str, Any] = {"entry": self.entry, "compiled": self.compiled}
        fields_.update(overrides)
        return EntryConfiguration(**fields_)

    def factories(self, **overrides: Any) -> PermissionProbeFactories:
        build = self.constructions.factory
        fields_: dict[str, Any] = {
            "environment_names": lambda: list(self.environment_names),
            "environment": self.environment.get,
            "metadata_fetch": self.metadata.fetch,
            "ssm": build("ssm", self.ssm),
            "sts": build("sts", self.sts),
            "operation_client": self.operation_client,
            "now": self.clock.now,
            "monotonic": self.clock.monotonic,
            "sleep": self.clock.sleep,
            "cleanup": self.cleanup,
        }
        fields_.update(overrides)
        return PermissionProbeFactories(**fields_)

    def run(
        self, configuration: EntryConfiguration | None = None, **factory_overrides: Any
    ) -> TaskReceipt:
        return run_task_entry(
            entry=self.entry,
            configuration=self.configuration() if configuration is None else configuration,
            factories=self.factories(**factory_overrides),
        )


def permission_context(**overrides: Any) -> PermissionContext:
    """A permission context over the synthetic registration, for resolving probe targets."""
    from fixtures.production_launch import launch_inputs_document
    from kalpamani.data.production.sharadar.launch_records import parse_launch_inputs
    from kalpamani.data.production.sharadar.permission_cells import PermissionBinding

    fields_: dict[str, Any] = {
        "binding": PermissionBinding(
            environment_binding_sha256="ab" * 32,
            policy_declaration_sha256="cd" * 32,
            registration_sha256="ef" * 32,
            targets_sha256="12" * 32,
            partition="aws",
            region="us-east-1",
        ),
        "licensed_bucket": "synthetic-licensed-bucket",
        "inputs": parse_launch_inputs(encode(launch_inputs_document(probe=True))),
        "targets": PermissionTargets(
            foundation_task_role_arn=f"arn:aws:iam::{ACCOUNT}:role/kalpamani-foundation-task",
            qualification_secret_arn=(
                f"arn:aws:secretsmanager:us-east-1:{ACCOUNT}:secret:synthetic-qual-AbCdEf"
            ),
            control_bucket_name="synthetic-control-bucket",
        ),
        "production_secret": "synthetic/production/sharadar",
    }
    fields_.update(overrides)
    return PermissionContext(**fields_)


__all__ = [
    "ACQ",
    "BUILD",
    "CONTAINER_URI",
    "METADATA_URI",
    "ORIGIN_ADDRESSES",
    "TASK_ENVIRONMENT_NAMES",
    "AcquisitionHarness",
    "BuildHarness",
    "Constructions",
    "FakeOperationClient",
    "FakeProbe",
    "FakeSts",
    "MetadataSource",
    "ProbeHarness",
    "VerificationHarness",
    "permission_context",
    "resolve_inside",
    "resolve_outside",
]
