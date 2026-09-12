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
    INTERFACE_ID,
    SUBNET_ID,
    TASK_ARN,
    FakeClientError,
    FakeSsm,
    binding_document,
    build_input_document,
    compiled_task,
    encode,
    metadata_document,
    revision_arn,
    task_identity_arn,
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
    INPUT_SCHEMA_VERSION,
    input_digest,
    ledger_digest,
    parse_slice,
)
from kalpamani.data.production.sharadar.metadata import METADATA_URI_ENV_VAR
from kalpamani.data.production.sharadar.plan import plan_digest_for
from kalpamani.data.production.sharadar.release import build_release_document
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
    ) -> None:
        constants = constants_for(ACQ)
        self.run_id = run_id
        slice_doc = slice_for_run(run) if slice_doc is None else slice_doc
        digest = plan_digest_for(parse_slice(slice_doc), acquisition_mode=AcquisitionMode.BACKFILL)
        self.input_bytes = encode(
            {
                "schema_version": INPUT_SCHEMA_VERSION,
                "contract_id": constants.input_contract_id,
                "run_identity": run_id,
                "slice": slice_doc,
                "plan_digest": digest,
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
        self.environment: dict[str, str] = {METADATA_URI_ENV_VAR: METADATA_URI}
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
        self.environment: dict[str, str] = {METADATA_URI_ENV_VAR: METADATA_URI}

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


__all__ = [
    "ACQ",
    "BUILD",
    "METADATA_URI",
    "ORIGIN_ADDRESSES",
    "TASK_ENVIRONMENT_NAMES",
    "AcquisitionHarness",
    "BuildHarness",
    "Constructions",
    "FakeSts",
    "MetadataSource",
    "resolve_inside",
    "resolve_outside",
]
