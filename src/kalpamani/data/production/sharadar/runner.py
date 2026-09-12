"""The task-side and human-side bootstrap sequences (ADR-0036 §2.12, steps 4-6a).

**The order is the security property, and it is preserved from the accepted
paths**: environment, then binding, then input, then self-check, then identity
proof, then the release barrier -- and every refusal before the barrier happens
with **zero** S3, secret and provider operations, because nothing in this module
holds a client that could perform one.

**Binding before identity.** The binding is *input* to the identity gate: the
gate compares the authenticated account to the binding's account and the
authenticated role name to the compiled task-role name. Loading is not proof,
and no operation past the gate is reachable without it.

**Processing is not implemented, and the runner says so.** After the barrier
passes, the sequence halts at ``HALTED_PROCESSING_NOT_IMPLEMENTED``: no
acquisition (secret retrieval, provider request, Bronze publication, locator) and
no build (locator read, exact reads, Silver/Gold publication) exists in this
repository, and this module claims neither. The counts it reports for those
operations are zero because they are zero.

The human path has the same shape with the private file in place of the
parameter, and no barrier: a human actor's placement is not verified because it
is not compute.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from kalpamani.data.production.sharadar.barrier import (
    BarrierOutcome,
    BarrierResult,
    await_placement_release,
)
from kalpamani.data.production.sharadar.bindings import (
    ParameterReader,
    ProductionRuntimeBinding,
    load_human_runtime_binding,
    load_task_runtime_binding,
)
from kalpamani.data.production.sharadar.identity import (
    ProvenIdentity,
    production_identity_refusal,
)
from kalpamani.data.production.sharadar.inputs import (
    InputError,
    decode_input,
    input_digest,
    parse_acquisition_input,
    parse_build_input,
)
from kalpamani.data.production.sharadar.metadata import (
    CompiledTask,
    parse_task_metadata,
    self_check_refusal,
    task_environment_refusal,
)
from kalpamani.data.production.sharadar.outcomes import OperationCounts, RunnerOutcome
from kalpamani.data.production.sharadar.release import ReleaseError, ReleaseExpectation
from kalpamani.data.production.sharadar.vocabulary import (
    IdentityPath,
    ProductionActor,
    constants_for,
)
from kalpamani.data.qualify.sharadar.runtime_binding import FileSecurity, RuntimeBindingError


class RunnerStage(StrEnum):
    """The last stage the task-side sequence definitively reached."""

    ENVIRONMENT = "ENVIRONMENT"
    BINDING = "BINDING"
    INPUT = "INPUT"
    SELF_CHECK = "SELF_CHECK"
    IDENTITY = "IDENTITY"
    RELEASE_BARRIER = "RELEASE_BARRIER"
    PROCESSING = "PROCESSING"


@dataclass(frozen=True, slots=True, kw_only=True)
class RunnerAdapters:
    """Everything the task-side sequence touches, injected. No client is built here.

    ``environment_names`` yields variable **names** only; ``parameters`` reads one
    exact parameter; ``metadata`` returns the decoded task metadata v4 document;
    ``caller_identity`` returns the decoded ``sts:GetCallerIdentity`` response.
    """

    environment_names: Callable[[], Iterable[str]]
    parameters: ParameterReader
    metadata: Callable[[], object]
    caller_identity: Callable[[], object]
    now: Callable[[], datetime]
    monotonic: Callable[[], float]
    sleep: Callable[[float], None]


@dataclass(frozen=True, slots=True, kw_only=True)
class RunnerReport:
    """The sanitized task-side result: outcome, stage, counts, barrier verdict."""

    outcome: RunnerOutcome
    stage: RunnerStage
    counts: OperationCounts
    barrier: BarrierResult | None

    def __post_init__(self) -> None:
        """Closed members and integers; data-plane counts are zero in this cycle."""
        if type(self.outcome) is not RunnerOutcome or type(self.stage) is not RunnerStage:
            raise TypeError("outcome and stage must be exact members")
        if type(self.counts) is not OperationCounts:
            raise TypeError("counts must be an exact OperationCounts")
        if self.counts.data_plane_operations != 0:
            raise ValueError("no data-plane operation exists in this cycle; the count must be zero")

    def __repr__(self) -> str:
        """Outcome and stage only."""
        return f"RunnerReport(outcome={self.outcome.value!r}, stage={self.stage.value!r})"


def _parse_input(
    actor: ProductionActor,
    document: dict[str, Any],
    *,
    now: datetime,
    expected_plan_digest: str | None,
    is_spent: Callable[[str], bool],
) -> str:
    """The identity the input names, after the actor's own contract admitted it."""
    if actor is ProductionActor.ACQUISITION:
        return parse_acquisition_input(
            document, now=now, expected_plan_digest=expected_plan_digest, is_spent=is_spent
        ).run_identity
    return parse_build_input(document, now=now).build_identity


def run_task_bootstrap(
    *,
    actor: ProductionActor,
    compiled: CompiledTask,
    adapters: RunnerAdapters,
    expected_plan_digest: str | None,
    is_spent: Callable[[str], bool],
) -> RunnerReport:
    """The task-side sequence through the release barrier; one sanitized report.

    ``expected_plan_digest`` and ``is_spent`` serve the acquisition input contract
    and are ignored for a build; both are injected because no compiled production
    plan and no spent-identity registry exist in this repository.
    """
    if type(actor) is not ProductionActor or type(compiled) is not CompiledTask:
        raise TypeError("actor and compiled must be exact values")
    if compiled.actor is not actor:
        raise ValueError("the compiled task is not this actor's")
    if type(adapters) is not RunnerAdapters:
        raise TypeError("adapters must be an exact RunnerAdapters")
    counts = OperationCounts()

    # Step 4a: the environment must be clean. Names only; no value is read.
    if task_environment_refusal(adapters.environment_names()) is not None:
        return RunnerReport(
            outcome=RunnerOutcome.REFUSED_ENVIRONMENT,
            stage=RunnerStage.ENVIRONMENT,
            counts=counts,
            barrier=None,
        )

    # Step 4b: the binding, from the one compiled parameter.
    counts = replace(counts, parameter_reads=counts.parameter_reads + 1)
    try:
        binding: ProductionRuntimeBinding = load_task_runtime_binding(
            actor, reader=adapters.parameters
        )
    except RuntimeBindingError:
        return RunnerReport(
            outcome=RunnerOutcome.REFUSED_BINDING,
            stage=RunnerStage.BINDING,
            counts=counts,
            barrier=None,
        )

    # Step 4c: the input, from the one compiled parameter; its digest over the bytes.
    counts = replace(counts, parameter_reads=counts.parameter_reads + 1)
    try:
        raw_input = adapters.parameters.read_parameter(constants_for(actor).input_parameter)
        digest = input_digest(raw_input)
        identity = _parse_input(
            actor,
            decode_input(raw_input),
            now=adapters.now(),
            expected_plan_digest=expected_plan_digest,
            is_spent=is_spent,
        )
    except (InputError, Exception):
        return RunnerReport(
            outcome=RunnerOutcome.REFUSED_INPUT,
            stage=RunnerStage.INPUT,
            counts=counts,
            barrier=None,
        )

    # Step 5: the self-check over documented metadata fields.
    try:
        metadata = parse_task_metadata(adapters.metadata())
    except Exception:
        metadata = None
    if metadata is None or self_check_refusal(metadata, compiled) is not None:
        return RunnerReport(
            outcome=RunnerOutcome.REFUSED_SELF_CHECK,
            stage=RunnerStage.SELF_CHECK,
            counts=counts,
            barrier=None,
        )

    # Step 6: one identity proof; account from the binding, role from the constants.
    counts = replace(counts, identity_calls=counts.identity_calls + 1)
    proof = production_identity_refusal(
        actor, path=IdentityPath.TASK, binding=binding, caller_identity=adapters.caller_identity
    )
    if type(proof) is not ProvenIdentity or proof.task_id != metadata.task_id:
        return RunnerReport(
            outcome=RunnerOutcome.REFUSED_IDENTITY,
            stage=RunnerStage.IDENTITY,
            counts=counts,
            barrier=None,
        )

    # Step 6a: the release barrier, bounded, on the expectation the task holds.
    try:
        expectation = ReleaseExpectation(
            actor=actor,
            task_arn=metadata.task_arn,
            task_definition_arn=metadata.task_definition_arn(),
            identity=identity,
            input_digest=digest,
        )
    except ReleaseError:
        return RunnerReport(
            outcome=RunnerOutcome.REFUSED_SELF_CHECK,
            stage=RunnerStage.SELF_CHECK,
            counts=counts,
            barrier=None,
        )
    barrier = await_placement_release(
        reader=adapters.parameters,
        expectation=expectation,
        now=adapters.now,
        monotonic=adapters.monotonic,
        sleep=adapters.sleep,
    )
    counts = replace(counts, parameter_reads=counts.parameter_reads + barrier.reads)
    if barrier.outcome is not BarrierOutcome.RELEASED:
        outcome = {
            BarrierOutcome.REFUSED_NO_RELEASE: RunnerOutcome.REFUSED_NO_RELEASE,
            BarrierOutcome.REFUSED_RELEASE_MISMATCH: RunnerOutcome.REFUSED_RELEASE_MISMATCH,
            BarrierOutcome.REFUSED_RELEASE_READ: RunnerOutcome.REFUSED_RELEASE_READ,
        }[barrier.outcome]
        return RunnerReport(
            outcome=outcome, stage=RunnerStage.RELEASE_BARRIER, counts=counts, barrier=barrier
        )

    # Step 7 does not exist in this repository. Halt, and say so.
    return RunnerReport(
        outcome=RunnerOutcome.HALTED_PROCESSING_NOT_IMPLEMENTED,
        stage=RunnerStage.PROCESSING,
        counts=counts,
        barrier=barrier,
    )


class HumanBootstrapOutcome(StrEnum):
    """The human-side sequence's one verdict. Closed."""

    REFUSED_BINDING = "REFUSED_BINDING"
    REFUSED_IDENTITY = "REFUSED_IDENTITY"
    IDENTITY_PROVEN = "IDENTITY_PROVEN"


@dataclass(frozen=True, slots=True, kw_only=True)
class HumanBootstrapReport:
    """The sanitized human-side result. The binding is returned only on proof."""

    outcome: HumanBootstrapOutcome
    binding: ProductionRuntimeBinding | None
    identity_calls: int

    def __post_init__(self) -> None:
        """A binding is present exactly when identity was proven."""
        if type(self.outcome) is not HumanBootstrapOutcome:
            raise TypeError("outcome must be an exact HumanBootstrapOutcome member")
        proven = self.outcome is HumanBootstrapOutcome.IDENTITY_PROVEN
        if proven != (self.binding is not None):
            raise ValueError("a binding is present exactly when identity was proven")

    def __repr__(self) -> str:
        """Outcome only."""
        return f"HumanBootstrapReport(outcome={self.outcome.value!r})"


def human_bootstrap(
    *,
    actor: ProductionActor,
    path: IdentityPath,
    environment: Callable[[str], str | None],
    caller_identity: Callable[[], object],
    root_source: Callable[[], Path] | None = None,
    security_of: Callable[[Path], FileSecurity] | None = None,
) -> HumanBootstrapReport:
    """The human-side sequence: private binding file, then identity proof.

    ``path`` is ``HUMAN`` for the actor's own permission set or ``LAUNCHER`` for
    its launcher set; a task path is refused here, because a human never proves a
    task identity.
    """
    if type(actor) is not ProductionActor or type(path) is not IdentityPath:
        raise TypeError("actor and path must be exact members")
    if path is IdentityPath.TASK:
        raise ValueError("a human bootstrap never proves a task identity")
    try:
        binding = load_human_runtime_binding(
            actor, environment=environment, root_source=root_source, security_of=security_of
        )
    except RuntimeBindingError:
        return HumanBootstrapReport(
            outcome=HumanBootstrapOutcome.REFUSED_BINDING, binding=None, identity_calls=0
        )
    proof = production_identity_refusal(
        actor, path=path, binding=binding, caller_identity=caller_identity
    )
    if type(proof) is not ProvenIdentity:
        return HumanBootstrapReport(
            outcome=HumanBootstrapOutcome.REFUSED_IDENTITY, binding=None, identity_calls=1
        )
    return HumanBootstrapReport(
        outcome=HumanBootstrapOutcome.IDENTITY_PROVEN, binding=binding, identity_calls=1
    )


__all__ = [
    "HumanBootstrapOutcome",
    "HumanBootstrapReport",
    "RunnerAdapters",
    "RunnerReport",
    "RunnerStage",
    "human_bootstrap",
    "run_task_bootstrap",
]
