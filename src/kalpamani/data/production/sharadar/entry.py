"""The two production task entries: closed selection, one receipt, one exit code.

**What an entry is.** The task definition's ``command`` is one token -- the actor's
entry name (ADR-0036 §2.9) -- and that token is the whole of entry selection: exactly
one argument, equal to one of two closed names, or the runner refuses before it looks
anything up. There is no flag, no environment-driven mode and no default actor.

**What this module does not do.** It constructs no client, reads no environment value,
performs no processing and holds neither actor's dependencies: the acquisition entry
lives in :mod:`acquisition_entry` and the build entry in :mod:`build_entry`, each
importing only what its actor may hold (ADR-0036 acceptance guard A-8), and
:func:`run_task_entry` reaches the selected one lazily so that importing this module
pulls in neither. What is shared is the vocabulary: the entry names, the compiled
configuration shape, the closed task outcome with its exit code and allowlisted
sentence, and the receipt every run ends with.

**The receipt is the task's whole public output** (ADR-0036 §2.12 step 8): one
allowlisted sentence, the bootstrap's own outcome where one exists, integer counts as
the adapters observed them, and any cleanup failure named by stage and category
**beside** the primary outcome, never in place of it. Exit ``0`` is ``COMPLETED`` and
nothing else; a completed run is a command status, never a data verdict.

**Accounting is observed or it is uncertain.** A processing path that raised past its
own reporting is classified ``UNCLASSIFIED`` with ``counts_observed = False``; the
receipt then carries the zero counts it can prove and says so, rather than a number
nobody measured.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

from kalpamani.data.production.sharadar.build_manifest import BuildConfiguration
from kalpamani.data.production.sharadar.metadata import CompiledTask
from kalpamani.data.production.sharadar.outcomes import (
    CleanupFailure,
    CleanupStage,
    OperationCounts,
    RunnerOutcome,
    count_lines,
    runner_sentence,
)
from kalpamani.data.production.sharadar.vocabulary import ProductionActor

if TYPE_CHECKING:  # pragma: no cover - typing only; the modules are imported lazily
    from kalpamani.data.production.sharadar.acquisition_entry import AcquisitionFactories
    from kalpamani.data.production.sharadar.build_entry import BuildFactories


class TaskEntry(StrEnum):
    """The two entry names, exactly as the task definitions' ``command`` spells them."""

    ACQUISITION = "kalpamani-production-acquire"
    BUILD = "kalpamani-research-build"


#: Which actor each entry runs as. Two entries, two actors, no third.
ENTRY_ACTOR: Final[dict[TaskEntry, ProductionActor]] = {
    TaskEntry.ACQUISITION: ProductionActor.ACQUISITION,
    TaskEntry.BUILD: ProductionActor.BUILD,
}


def select_entry(arguments: Sequence[object]) -> TaskEntry | None:
    """The entry exactly one argument names, or ``None``.

    ``arguments`` are the arguments after the program name. Anything but exactly one
    string equal to a member's value -- an extra argument, a flag, an empty list, a
    near-miss -- selects nothing, and a caller with nothing selected refuses.
    """
    if not isinstance(arguments, Sequence) or isinstance(arguments, str | bytes):
        return None
    if len(arguments) != 1 or type(arguments[0]) is not str:
        return None
    for entry in TaskEntry:
        if arguments[0] == entry.value:
            return entry
    return None


class TaskOutcome(StrEnum):
    """The task's one public verdict. Closed; every member has an exit code and a sentence."""

    COMPLETED = "COMPLETED"
    REFUSED_ENTRY = "REFUSED_ENTRY"
    REFUSED_CONFIGURATION = "REFUSED_CONFIGURATION"
    REFUSED_CREDENTIAL_ENVIRONMENT = "REFUSED_CREDENTIAL_ENVIRONMENT"
    REFUSED_ORIGIN = "REFUSED_ORIGIN"
    REFUSED_DEPENDENCY = "REFUSED_DEPENDENCY"
    REFUSED_ENVIRONMENT = "REFUSED_ENVIRONMENT"
    REFUSED_BINDING = "REFUSED_BINDING"
    REFUSED_INPUT = "REFUSED_INPUT"
    REFUSED_SELF_CHECK = "REFUSED_SELF_CHECK"
    REFUSED_IDENTITY = "REFUSED_IDENTITY"
    REFUSED_NO_RELEASE = "REFUSED_NO_RELEASE"
    REFUSED_RELEASE_MISMATCH = "REFUSED_RELEASE_MISMATCH"
    REFUSED_RELEASE_READ = "REFUSED_RELEASE_READ"
    REFUSED_RESERVATION = "REFUSED_RESERVATION"
    REFUSED_CREDENTIAL = "REFUSED_CREDENTIAL"
    ACQUISITION_HALTED = "ACQUISITION_HALTED"
    LOCATOR_NOT_PUBLISHED = "LOCATOR_NOT_PUBLISHED"
    LOCATOR_STATE_UNKNOWN = "LOCATOR_STATE_UNKNOWN"
    LOCATOR_NAME_OCCUPIED = "LOCATOR_NAME_OCCUPIED"
    REFUSED_INPUTS = "REFUSED_INPUTS"
    REFUSED_NORMALIZATION = "REFUSED_NORMALIZATION"
    REFUSED_TIMING = "REFUSED_TIMING"
    REFUSED_QUALITY = "REFUSED_QUALITY"
    REFUSED_VERIFICATION = "REFUSED_VERIFICATION"
    BUILD_HALTED = "BUILD_HALTED"
    MANIFEST_NAME_OCCUPIED = "MANIFEST_NAME_OCCUPIED"
    MANIFEST_STATE_UNKNOWN = "MANIFEST_STATE_UNKNOWN"
    MANIFEST_REFUSED = "MANIFEST_REFUSED"
    UNCLASSIFIED = "UNCLASSIFIED"


#: The exit status of every outcome. ``0`` is ``COMPLETED`` alone; no default, no else.
EXIT_STATUS: Final[dict[TaskOutcome, int]] = {
    TaskOutcome.COMPLETED: 0,
    TaskOutcome.REFUSED_ENTRY: 2,
    TaskOutcome.REFUSED_CONFIGURATION: 3,
    TaskOutcome.REFUSED_CREDENTIAL_ENVIRONMENT: 4,
    TaskOutcome.REFUSED_ORIGIN: 5,
    TaskOutcome.REFUSED_DEPENDENCY: 6,
    TaskOutcome.REFUSED_ENVIRONMENT: 10,
    TaskOutcome.REFUSED_BINDING: 11,
    TaskOutcome.REFUSED_INPUT: 12,
    TaskOutcome.REFUSED_SELF_CHECK: 13,
    TaskOutcome.REFUSED_IDENTITY: 14,
    TaskOutcome.REFUSED_NO_RELEASE: 15,
    TaskOutcome.REFUSED_RELEASE_MISMATCH: 16,
    TaskOutcome.REFUSED_RELEASE_READ: 17,
    TaskOutcome.REFUSED_RESERVATION: 20,
    TaskOutcome.REFUSED_CREDENTIAL: 21,
    TaskOutcome.ACQUISITION_HALTED: 22,
    TaskOutcome.LOCATOR_NOT_PUBLISHED: 23,
    TaskOutcome.LOCATOR_STATE_UNKNOWN: 24,
    TaskOutcome.LOCATOR_NAME_OCCUPIED: 25,
    TaskOutcome.REFUSED_INPUTS: 30,
    TaskOutcome.REFUSED_NORMALIZATION: 31,
    TaskOutcome.REFUSED_TIMING: 32,
    TaskOutcome.REFUSED_QUALITY: 33,
    TaskOutcome.REFUSED_VERIFICATION: 34,
    TaskOutcome.BUILD_HALTED: 35,
    TaskOutcome.MANIFEST_NAME_OCCUPIED: 36,
    TaskOutcome.MANIFEST_STATE_UNKNOWN: 37,
    TaskOutcome.MANIFEST_REFUSED: 38,
    TaskOutcome.UNCLASSIFIED: 40,
}

#: The one allowlisted sentence per outcome. No key, digest, identifier, ARN or row.
TASK_SENTENCES: Final[dict[TaskOutcome, str]] = {
    TaskOutcome.COMPLETED: "production task completed: every operation confirmed",
    TaskOutcome.REFUSED_ENTRY: "production task refused: no closed entry was selected",
    TaskOutcome.REFUSED_CONFIGURATION: (
        "production task refused: the compiled configuration is incomplete"
    ),
    TaskOutcome.REFUSED_CREDENTIAL_ENVIRONMENT: (
        "production task refused: the credential environment is not a task's"
    ),
    TaskOutcome.REFUSED_ORIGIN: (
        "production task refused: the provider origin is outside the compiled address set"
    ),
    TaskOutcome.REFUSED_DEPENDENCY: "production task refused: a dependency could not be built",
    TaskOutcome.REFUSED_ENVIRONMENT: "production task refused: the task environment is not clean",
    TaskOutcome.REFUSED_BINDING: "production task refused: the runtime binding did not validate",
    TaskOutcome.REFUSED_INPUT: "production task refused: the input did not validate",
    TaskOutcome.REFUSED_SELF_CHECK: "production task refused: the task self-check did not pass",
    TaskOutcome.REFUSED_IDENTITY: "production task refused: the identity proof did not pass",
    TaskOutcome.REFUSED_NO_RELEASE: "production task refused: no placement release arrived",
    TaskOutcome.REFUSED_RELEASE_MISMATCH: (
        "production task refused: the placement release did not match"
    ),
    TaskOutcome.REFUSED_RELEASE_READ: (
        "production task refused: the placement release could not be read"
    ),
    TaskOutcome.REFUSED_RESERVATION: (
        "production task refused: the run identity could not be reserved"
    ),
    TaskOutcome.REFUSED_CREDENTIAL: (
        "production task refused: the provider credential could not be retrieved"
    ),
    TaskOutcome.ACQUISITION_HALTED: "production task halted: the acquisition stopped short",
    TaskOutcome.LOCATOR_NOT_PUBLISHED: "production task halted: no locator was published",
    TaskOutcome.LOCATOR_STATE_UNKNOWN: (
        "production task halted: the locator publication state is unknown"
    ),
    TaskOutcome.LOCATOR_NAME_OCCUPIED: "production task halted: the locator name was occupied",
    TaskOutcome.REFUSED_INPUTS: "production task refused: the build inputs did not verify",
    TaskOutcome.REFUSED_NORMALIZATION: (
        "production task refused: normalization did not admit the inputs"
    ),
    TaskOutcome.REFUSED_TIMING: "production task refused: availability timing did not resolve",
    TaskOutcome.REFUSED_QUALITY: "production task refused: a quality check did not pass",
    TaskOutcome.REFUSED_VERIFICATION: "production task refused: adjusted rows did not verify",
    TaskOutcome.BUILD_HALTED: "production task halted: the build stopped short",
    TaskOutcome.MANIFEST_NAME_OCCUPIED: "production task halted: the manifest name was occupied",
    TaskOutcome.MANIFEST_STATE_UNKNOWN: (
        "production task halted: the manifest publication state is unknown"
    ),
    TaskOutcome.MANIFEST_REFUSED: "production task halted: the manifest was refused",
    TaskOutcome.UNCLASSIFIED: (
        "production task failed: an unclassified error; accounting is uncertain"
    ),
}

#: How a bootstrap refusal becomes a task outcome. The two non-refusal members are
#: not here: a released bootstrap continues into processing, and the bootstrap-only
#: halt never occurs on a composed entry.
BOOTSTRAP_OUTCOME: Final[dict[RunnerOutcome, TaskOutcome]] = {
    RunnerOutcome.REFUSED_ENVIRONMENT: TaskOutcome.REFUSED_ENVIRONMENT,
    RunnerOutcome.REFUSED_BINDING: TaskOutcome.REFUSED_BINDING,
    RunnerOutcome.REFUSED_INPUT: TaskOutcome.REFUSED_INPUT,
    RunnerOutcome.REFUSED_SELF_CHECK: TaskOutcome.REFUSED_SELF_CHECK,
    RunnerOutcome.REFUSED_IDENTITY: TaskOutcome.REFUSED_IDENTITY,
    RunnerOutcome.REFUSED_NO_RELEASE: TaskOutcome.REFUSED_NO_RELEASE,
    RunnerOutcome.REFUSED_RELEASE_MISMATCH: TaskOutcome.REFUSED_RELEASE_MISMATCH,
    RunnerOutcome.REFUSED_RELEASE_READ: TaskOutcome.REFUSED_RELEASE_READ,
}


def task_sentence(outcome: TaskOutcome) -> str:
    """The one allowlisted sentence for a task outcome. An exact member only."""
    if type(outcome) is not TaskOutcome:
        raise TypeError("outcome must be an exact TaskOutcome member")
    return TASK_SENTENCES[outcome]


@dataclass(frozen=True, slots=True, kw_only=True)
class EntryConfiguration:
    """What the image compiles for one entry, beyond the accepted :class:`CompiledTask`.

    ``secret_identifier`` and ``origin_addresses`` belong to the acquisition entry and
    must be absent for the build; ``build_configuration`` belongs to the build entry and
    must be absent for acquisition. The shape refuses a configuration that hands either
    actor the other's capability, and each entry additionally refuses at run time when
    what it needs is missing -- **before** any client exists.

    How these values reach the image is proposed, not accepted (ADR-0043); nothing here
    reads them from a binding, an input, a release or the environment.
    """

    entry: TaskEntry
    compiled: CompiledTask
    secret_identifier: str | None = None
    origin_addresses: frozenset[str] = field(default_factory=frozenset)
    build_configuration: BuildConfiguration | None = None

    def __post_init__(self) -> None:
        """Exact members; the compiled task is this entry's actor's; no crossed capability."""
        if type(self.entry) is not TaskEntry or type(self.compiled) is not CompiledTask:
            raise TypeError("entry and compiled must be exact values")
        if self.compiled.actor is not ENTRY_ACTOR[self.entry]:
            raise ValueError("the compiled task is not this entry's actor")
        if type(self.origin_addresses) is not frozenset:
            raise TypeError("origin_addresses must be a frozenset")
        if self.secret_identifier is not None and type(self.secret_identifier) is not str:
            raise TypeError("secret_identifier must be a string or None")
        if self.build_configuration is not None and (
            type(self.build_configuration) is not BuildConfiguration
        ):
            raise TypeError("build_configuration must be a BuildConfiguration or None")
        if self.entry is TaskEntry.BUILD and (
            self.secret_identifier is not None or self.origin_addresses
        ):
            raise ValueError("a build entry holds no secret identifier and no provider origin")
        if self.entry is TaskEntry.ACQUISITION and self.build_configuration is not None:
            raise ValueError("an acquisition entry holds no build configuration")

    def __repr__(self) -> str:
        """The entry only. **Never the secret identifier, never an address.**"""
        return f"EntryConfiguration(entry={self.entry.value!r})"


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskReceipt:
    """The task's sanitized terminal record: outcome, bootstrap verdict, counts, cleanup.

    ``counts_observed`` is ``False`` exactly when the outcome is ``UNCLASSIFIED``: the
    counts are then the zeros the entry can prove, not a measurement.
    """

    entry: TaskEntry
    outcome: TaskOutcome
    runner: RunnerOutcome | None
    counts: OperationCounts
    counts_observed: bool
    cleanup_failures: tuple[CleanupFailure, ...]

    def __post_init__(self) -> None:
        """Closed members and integers; uncertainty exactly where it is."""
        if type(self.entry) is not TaskEntry or type(self.outcome) is not TaskOutcome:
            raise TypeError("entry and outcome must be exact members")
        if self.runner is not None and type(self.runner) is not RunnerOutcome:
            raise TypeError("runner must be an exact RunnerOutcome member or None")
        if type(self.counts) is not OperationCounts:
            raise TypeError("counts must be an exact OperationCounts")
        if type(self.counts_observed) is not bool:
            raise TypeError("counts_observed must be a bool")
        if self.counts_observed == (self.outcome is TaskOutcome.UNCLASSIFIED):
            raise ValueError("counts are observed exactly when the outcome is classified")
        if any(type(failure) is not CleanupFailure for failure in self.cleanup_failures):
            raise TypeError("cleanup failures must be exact CleanupFailure values")
        if self.outcome is TaskOutcome.COMPLETED and self.runner is not RunnerOutcome.RELEASED:
            raise ValueError("a completed task was released")

    @property
    def exit_code(self) -> int:
        """The closed exit status of this outcome."""
        return EXIT_STATUS[self.outcome]

    def render(self) -> tuple[str, ...]:
        """The allowlisted lines, in order: sentence, bootstrap verdict, counts, cleanup."""
        lines = [task_sentence(self.outcome)]
        if self.runner is not None:
            lines.append(f"bootstrap: {runner_sentence(self.runner)}")
        lines.append(f"counts_observed={'true' if self.counts_observed else 'false'}")
        lines.extend(count_lines(self.counts))
        for failure in self.cleanup_failures:
            reason = failure.failure
            category = reason if isinstance(reason, str) else reason.value
            lines.append(f"cleanup_failure={failure.stage.value}:{category}")
        return tuple(lines)

    def __repr__(self) -> str:
        """Entry and outcome only."""
        return f"TaskReceipt(entry={self.entry.value!r}, outcome={self.outcome.value!r})"


def run_cleanup(cleanup: Callable[[], None] | None) -> tuple[CleanupFailure, ...]:
    """Run the working-directory cleanup, if any; report its failure beside the outcome.

    The cleanup's own exception is never carried: a path is exactly what it would say.
    """
    if cleanup is None:
        return ()
    try:
        cleanup()
    except Exception:
        return (CleanupFailure(stage=CleanupStage.WORKING_DIRECTORY, failure="CLEANUP_RAISED"),)
    return ()


def pre_entry_refusal(
    *,
    entry: TaskEntry,
    configuration: EntryConfiguration,
    environment_names: Callable[[], Any],
) -> TaskOutcome | None:
    """The checks every entry makes before it constructs anything, in order.

    The configuration must be this entry's, and the credential environment must be a
    task's. Both are answered from compiled values and variable names alone.
    """
    from kalpamani.data.production.sharadar.task_clients import (
        task_credential_environment_refusal,
    )

    if type(configuration) is not EntryConfiguration or configuration.entry is not entry:
        return TaskOutcome.REFUSED_CONFIGURATION
    try:
        names = list(environment_names())
    except Exception:
        return TaskOutcome.REFUSED_CREDENTIAL_ENVIRONMENT
    if task_credential_environment_refusal(names) is not None:
        return TaskOutcome.REFUSED_CREDENTIAL_ENVIRONMENT
    return None


def refusal_receipt(
    entry: TaskEntry,
    outcome: TaskOutcome,
    *,
    cleanup: Callable[[], None] | None = None,
    runner: RunnerOutcome | None = None,
    counts: OperationCounts | None = None,
) -> TaskReceipt:
    """A receipt for a refusal made before or beside processing, cleanup included."""
    return TaskReceipt(
        entry=entry,
        outcome=outcome,
        runner=runner,
        counts=OperationCounts() if counts is None else counts,
        counts_observed=outcome is not TaskOutcome.UNCLASSIFIED,
        cleanup_failures=run_cleanup(cleanup),
    )


def run_task_entry(
    *,
    entry: TaskEntry | None,
    configuration: EntryConfiguration | None,
    factories: AcquisitionFactories | BuildFactories | None,
) -> TaskReceipt:
    """Dispatch to the selected entry. ``None`` anywhere is a refusal, not a default.

    The actor modules are imported here, lazily, so that importing this module
    imports neither actor's dependencies and each actor's image imports only its own.
    """
    if type(entry) is not TaskEntry:
        return TaskReceipt(
            entry=TaskEntry.BUILD,
            outcome=TaskOutcome.REFUSED_ENTRY,
            runner=None,
            counts=OperationCounts(),
            counts_observed=True,
            cleanup_failures=(),
        )
    if configuration is None or factories is None:
        return refusal_receipt(entry, TaskOutcome.REFUSED_CONFIGURATION)
    if entry is TaskEntry.ACQUISITION:
        from kalpamani.data.production.sharadar.acquisition_entry import (
            AcquisitionFactories,
            run_acquisition_entry,
        )

        if type(factories) is not AcquisitionFactories:
            return refusal_receipt(entry, TaskOutcome.REFUSED_CONFIGURATION)
        return run_acquisition_entry(configuration=configuration, factories=factories)
    from kalpamani.data.production.sharadar.build_entry import BuildFactories, run_build_entry

    if type(factories) is not BuildFactories:
        return refusal_receipt(entry, TaskOutcome.REFUSED_CONFIGURATION)
    return run_build_entry(configuration=configuration, factories=factories)


__all__ = [
    "BOOTSTRAP_OUTCOME",
    "ENTRY_ACTOR",
    "EXIT_STATUS",
    "TASK_SENTENCES",
    "EntryConfiguration",
    "TaskEntry",
    "TaskOutcome",
    "TaskReceipt",
    "pre_entry_refusal",
    "refusal_receipt",
    "run_cleanup",
    "run_task_entry",
    "select_entry",
    "task_sentence",
]
