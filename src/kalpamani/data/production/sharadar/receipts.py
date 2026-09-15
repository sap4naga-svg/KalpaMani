"""The task receipt as machine-readable evidence, its validator, and ledger completion.

ADR-0044 §5.

**One line, at the end of the task's output.** The accepted receipt (ADR-0043) is
allowlisted sentences and integer counts. This module adds one more line -- ``receipt:``
followed by one closed JSON document -- so that a future, separately authorized
workstation collector can read the task's terminal evidence from its log stream and
complete the owner ledger without inferring anything from prose. The line carries no
key, bucket, credential, identifier, subject or vendor row -- ADR-0036 §2.9's output rule
holds -- and binds itself to the run through one **binding digest**: a SHA-256 over the
values the launch tool already holds from its own launch record: the task id, the
task-definition ARN, the image digest, the run or build identity, the input digest, the
configuration digest and the code commit. The collector recomputes the digest from its
record and compares; the task discloses nothing it did not already prove, and a receipt
from another task, image, configuration or run cannot bind. The public code commit and
the registered configuration digest travel in the clear so a collector can tell *which*
build refused before it knows the run.

**A receipt states what it can prove.** Counts are present exactly when the task
observed them; ``counts_observed = false`` (an unclassified failure) carries ``null``
counts and can never be read as zeros. Bootstrap evidence is present exactly when the
bootstrap released; a refusal before the barrier carries none, and the collector binds
such a receipt to the launch through the launch record alone.

**The validator refuses incomplete, contradictory or duplicate evidence.** Exactly one
receipt line; a closed shape; an exit code that is the outcome's; a runner verdict that
agrees with the outcome; evidence agreeing with the launch record on every field; and a
digest over the document. A ledger row is completed only from a ``COMPLETED`` receipt
with observed counts; every other receipt yields the ledger outcome it names or --
for uncertain evidence -- no row at all, leaving the run for owner review.

**Collection is not implemented here.** How the collector reads the log stream, and
the ``logs:GetLogEvents`` permission it needs, are ADR-0044 §5's proposal; this module
is the offline parser the collector would call, exercised on synthetic evidence only.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, fields
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.production.sharadar.documents import (
    contains_surrogate_text,
    hex_digest,
    is_json_shaped,
)
from kalpamani.data.production.sharadar.entry import (
    BOOTSTRAP_OUTCOME,
    ENTRY_ACTOR,
    EXIT_STATUS,
    PROBE_ENTRIES,
    PROBE_OUTCOMES,
    VERIFICATION_ENTRIES,
    TaskEntry,
    TaskOutcome,
    TaskReceipt,
)
from kalpamani.data.production.sharadar.inputs import LEDGER_OUTCOMES
from kalpamani.data.production.sharadar.keys import RUN_ID_RE
from kalpamani.data.production.sharadar.metadata_grammar import (
    CODE_COMMIT_RE,
    CONFIGURATION_DIGEST_RE,
    IMAGE_DIGEST_RE,
)
from kalpamani.data.production.sharadar.outcomes import (
    CleanupFailure,
    CleanupStage,
    OperationCounts,
    RunnerOutcome,
)
from kalpamani.data.production.sharadar.permission_probe import (
    PermissionProbeObservation,
    parse_permission_probe_observation,
)
from kalpamani.data.production.sharadar.probe import ProbeObservation, parse_probe_observation
from kalpamani.data.production.sharadar.release import TASK_DEFINITION_ARN_RE
from kalpamani.data.production.sharadar.schema_observation import (
    SchemaObservation,
    parse_schema_observation,
)

#: Version 2 (proposed ADR-0045): two evidence blocks join the closed set -- the build
#: verification probe observation and the Route B per-dataset schema observation --
#: each carried exactly by the one outcome that produces it, and null everywhere else.
#: A v1 receipt is refused (SCHEMA_VERSION_UNKNOWN); no v1 receipt was ever emitted by a task.
#: Version 3 (proposed ADR-0048): one more closed, nullable block -- ``permission`` --
#: carried exactly by a permission-probe entry's PROBE_* receipt. A v2 validator refuses
#: the field; the collector and the workstation read v3 alone.
RECEIPT_CONTRACT_ID: Final = "kalpamani-task-receipt/v3"
RECEIPT_SCHEMA_VERSION: Final = 3
#: The prefix of the one machine-readable line. Everything after it is the document.
RECEIPT_LINE_PREFIX: Final = "receipt: "
MAX_RECEIPT_BYTES: Final = 8 * 1024

_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "entry",
        "actor",
        "outcome",
        "exit_code",
        "runner",
        "counts_observed",
        "counts",
        "cleanup_failures",
        "code_commit",
        "configuration_digest",
        "binding_digest",
        "probe",
        "schema_observation",
        "permission",
        "receipt_digest",
    }
)
_COUNT_FIELDS: Final[tuple[str, ...]] = tuple(f.name for f in fields(OperationCounts))

#: Outcomes reached before the accepted bootstrap ran at all: no runner verdict exists.
PRE_BOOTSTRAP_OUTCOMES: Final[frozenset[TaskOutcome]] = frozenset(
    {
        TaskOutcome.REFUSED_ENTRY,
        TaskOutcome.REFUSED_CONFIGURATION,
        TaskOutcome.REFUSED_CREDENTIAL_ENVIRONMENT,
        TaskOutcome.REFUSED_ORIGIN,
        TaskOutcome.REFUSED_DEPENDENCY,
        TaskOutcome.UNCLASSIFIED,
    }
)
#: Outcomes the accepted bootstrap refused with: the runner verdict names which.
BOOTSTRAP_REFUSALS: Final[frozenset[TaskOutcome]] = frozenset(BOOTSTRAP_OUTCOME.values())

#: The ledger outcome each task outcome maps to, where one can be completed without
#: owner review. ``None`` is *uncertain*: the evidence does not establish a row.
LEDGER_OUTCOME_OF: Final[dict[TaskOutcome, str | None]] = {
    TaskOutcome.COMPLETED: "COMPLETED",
    # A verified bootstrap consumed its identity for verification and completed no run:
    # the ledger row says VERIFIED, and can never say COMPLETED (proposed ADR-0045).
    TaskOutcome.VERIFIED_BOOTSTRAP: "VERIFIED",
    TaskOutcome.ACQUISITION_HALTED: "HALTED",
    TaskOutcome.BUILD_HALTED: "HALTED",
    TaskOutcome.LOCATOR_NOT_PUBLISHED: "HALTED",
    TaskOutcome.LOCATOR_STATE_UNKNOWN: None,
    TaskOutcome.LOCATOR_NAME_OCCUPIED: "HALTED",
    TaskOutcome.MANIFEST_NAME_OCCUPIED: "HALTED",
    TaskOutcome.MANIFEST_STATE_UNKNOWN: None,
    TaskOutcome.MANIFEST_REFUSED: "HALTED",
    TaskOutcome.UNCLASSIFIED: None,
    # A probe task issued its one operation or held (proposed ADR-0048): its identity
    # was consumed by a probe launch; the row says PROBED and never COMPLETED or
    # VERIFIED. What the operation answered is the permission record's, not the row's.
    TaskOutcome.PROBE_MATCHED: "PROBED",
    TaskOutcome.PROBE_INVERTED: "PROBED",
    TaskOutcome.PROBE_UNDECIDED: "PROBED",
    TaskOutcome.PROBE_HELD: "PROBED",
}


class ReceiptDefect(StrEnum):
    """Why a receipt was refused. Closed; carries no value."""

    NO_RECEIPT = "NO_RECEIPT"
    DUPLICATE_RECEIPT = "DUPLICATE_RECEIPT"
    TOO_LARGE = "TOO_LARGE"
    ENCODING_INVALID = "ENCODING_INVALID"
    DOCUMENT_MALFORMED = "DOCUMENT_MALFORMED"
    DUPLICATE_KEY = "DUPLICATE_KEY"
    SCHEMA_VERSION_UNKNOWN = "SCHEMA_VERSION_UNKNOWN"
    CONTRACT_ID_UNKNOWN = "CONTRACT_ID_UNKNOWN"
    FIELD_UNKNOWN = "FIELD_UNKNOWN"
    FIELD_MISSING = "FIELD_MISSING"
    FIELD_MALFORMED = "FIELD_MALFORMED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    EXIT_CODE_CONTRADICTS_OUTCOME = "EXIT_CODE_CONTRADICTS_OUTCOME"
    RUNNER_CONTRADICTS_OUTCOME = "RUNNER_CONTRADICTS_OUTCOME"
    COUNTS_CONTRADICT_OBSERVATION = "COUNTS_CONTRADICT_OBSERVATION"
    EVIDENCE_CONTRADICTS_OUTCOME = "EVIDENCE_CONTRADICTS_OUTCOME"
    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    ENTRY_MISMATCH = "ENTRY_MISMATCH"
    BINDING_MISMATCH = "BINDING_MISMATCH"
    CONFIGURATION_MISMATCH = "CONFIGURATION_MISMATCH"


class ReceiptError(Exception):
    """A refusal built from one closed member and nothing else."""

    __slots__ = ("defect",)

    def __init__(self, defect: ReceiptDefect) -> None:
        """Carry the defect."""
        if type(defect) is not ReceiptDefect:
            raise TypeError("defect must be an exact ReceiptDefect member")
        self.defect = defect
        super().__init__(f"task receipt: {defect.value}")


def _refuse(defect: ReceiptDefect) -> ReceiptError:
    return ReceiptError(defect)


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Refuse a repeated key anywhere in the document -- nested objects included.

    ``json.loads`` keeps the last of two values for one key, so a line carrying
    ``"outcome":"REFUSED_INPUT","outcome":"COMPLETED"`` would otherwise decode to a
    document that says ``COMPLETED`` and still carries a matching digest.
    """
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise _refuse(ReceiptDefect.DUPLICATE_KEY)
        seen[key] = value
    return seen


# ---------------------------------------------------------------------------
# Emitting
# ---------------------------------------------------------------------------


def binding_digest(
    *,
    task_id: str,
    task_definition_arn: str,
    image_digest: str,
    identity: str,
    input_digest: str,
    configuration_digest: str,
    code_commit: str,
) -> str:
    """The SHA-256 the task and the collector both compute over the launch-record values."""
    return sha256_hex(
        canonical_bytes(
            {
                "task_id": task_id,
                "task_definition_arn": task_definition_arn,
                "image_digest": image_digest,
                "identity": identity,
                "input_digest": input_digest,
                "configuration_digest": configuration_digest,
                "code_commit": code_commit,
            }
        )
    )


def receipt_document(receipt: TaskReceipt) -> dict[str, Any]:
    """The closed receipt document of one :class:`TaskReceipt`, digest included."""
    if type(receipt) is not TaskReceipt:
        raise TypeError("receipt must be an exact TaskReceipt")
    evidence = receipt.evidence
    bound: str | None = None
    if evidence is not None:
        assert receipt.configuration_digest is not None and receipt.code_commit is not None
        bound = binding_digest(
            task_id=evidence.task_id,
            task_definition_arn=evidence.task_definition_arn,
            image_digest=evidence.image_digest,
            identity=evidence.identity,
            input_digest=evidence.input_digest,
            configuration_digest=receipt.configuration_digest,
            code_commit=receipt.code_commit,
        )
    document: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "contract_id": RECEIPT_CONTRACT_ID,
        # An invalid invocation selected no entry and names no actor (ADR-0044 s.4).
        "entry": None if receipt.entry is None else receipt.entry.value,
        "actor": None if receipt.entry is None else ENTRY_ACTOR[receipt.entry].value,
        "outcome": receipt.outcome.value,
        "exit_code": receipt.exit_code,
        "runner": None if receipt.runner is None else receipt.runner.value,
        "counts_observed": receipt.counts_observed,
        "counts": (
            {name: getattr(receipt.counts, name) for name in _COUNT_FIELDS}
            if receipt.counts_observed
            else None
        ),
        "cleanup_failures": [
            {
                "stage": failure.stage.value,
                "failure": (
                    failure.failure if isinstance(failure.failure, str) else failure.failure.value
                ),
            }
            for failure in receipt.cleanup_failures
        ],
        "code_commit": receipt.code_commit,
        "configuration_digest": receipt.configuration_digest,
        "binding_digest": bound,
        "probe": None if receipt.probe is None else receipt.probe.document(),
        "schema_observation": (
            None if receipt.schema_observation is None else receipt.schema_observation.document()
        ),
        "permission": None if receipt.permission is None else receipt.permission.document(),
    }
    document["receipt_digest"] = sha256_hex(canonical_bytes(document))
    return document


def receipt_line(receipt: TaskReceipt) -> str:
    """The one machine-readable line: the prefix and the canonical document."""
    return RECEIPT_LINE_PREFIX + canonical_bytes(receipt_document(receipt)).decode("utf-8")


# ---------------------------------------------------------------------------
# Collecting and validating
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class ReceiptExpectation:
    """What the launch record already holds about the run a receipt must belong to.

    ``task_definition_arn`` and ``image_digest`` are what the launch tool observed and
    attested in the release; ``configuration_digest`` and ``code_commit`` the registered
    image-gate values; ``identity`` and ``input_digest`` the input it materialized.
    """

    entry: TaskEntry
    task_id: str
    task_definition_arn: str
    image_digest: str
    configuration_digest: str
    code_commit: str
    identity: str
    input_digest: str

    def __post_init__(self) -> None:
        """Every field to its grammar."""
        if type(self.entry) is not TaskEntry:
            raise _refuse(ReceiptDefect.FIELD_MALFORMED)
        checks = (
            (self.task_id, r"[0-9a-f]{32}"),
            (self.image_digest, IMAGE_DIGEST_RE.pattern),
            (self.configuration_digest, CONFIGURATION_DIGEST_RE.pattern),
            (self.code_commit, CODE_COMMIT_RE.pattern),
        )
        for value, pattern in checks:
            if type(value) is not str or re.fullmatch(pattern, value) is None:
                raise _refuse(ReceiptDefect.FIELD_MALFORMED)
        if TASK_DEFINITION_ARN_RE.fullmatch(self.task_definition_arn or "") is None:
            raise _refuse(ReceiptDefect.FIELD_MALFORMED)
        if type(self.identity) is not str or not RUN_ID_RE.match(self.identity):
            raise _refuse(ReceiptDefect.FIELD_MALFORMED)
        if hex_digest(self.input_digest) is None:
            raise _refuse(ReceiptDefect.FIELD_MALFORMED)

    def __repr__(self) -> str:
        """The entry only."""
        return f"ReceiptExpectation(entry={self.entry.value!r})"

    @property
    def binding_digest(self) -> str:
        """What a receipt from exactly this run must carry when its bootstrap released."""
        return binding_digest(
            task_id=self.task_id,
            task_definition_arn=self.task_definition_arn,
            image_digest=self.image_digest,
            identity=self.identity,
            input_digest=self.input_digest,
            configuration_digest=self.configuration_digest,
            code_commit=self.code_commit,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class VerifiedReceipt:
    """One receipt that passed every clause and is bound to the launch record.

    ``entry`` is ``None`` exactly for ``REFUSED_ENTRY``: the process selected no entry,
    and the receipt invents no actor for it.
    """

    entry: TaskEntry | None
    outcome: TaskOutcome
    runner: RunnerOutcome | None
    counts: OperationCounts | None
    cleanup_failures: tuple[CleanupFailure, ...]
    released: bool
    #: The build verification probe observation -- an observation, never a verdict.
    probe: ProbeObservation | None = None
    #: The Route B schema observation -- evidence for owner review, never an accepted set.
    schema_observation: SchemaObservation | None = None
    #: The permission-probe observation (proposed ADR-0048) -- what the probe's one
    #: operation answered; the workstation's permission record is completed from it.
    permission: PermissionProbeObservation | None = None

    @property
    def counts_observed(self) -> bool:
        """Whether the task measured its counts. ``False`` is uncertainty, not zero."""
        return self.counts is not None

    @property
    def ledger_outcome(self) -> str | None:
        """The ledger outcome this evidence establishes, or ``None`` for owner review."""
        if self.outcome in LEDGER_OUTCOME_OF:
            return LEDGER_OUTCOME_OF[self.outcome]
        if self.outcome in BOOTSTRAP_REFUSALS or self.outcome in PRE_BOOTSTRAP_OUTCOMES:
            return "REFUSED"
        return "REFUSED"

    def __repr__(self) -> str:
        """Entry and outcome only."""
        entry = None if self.entry is None else self.entry.value
        return f"VerifiedReceipt(entry={entry!r}, outcome={self.outcome.value!r})"


def collect_receipt_line(lines: Iterable[str]) -> str:
    """Exactly one receipt line from a task's output, or refuse."""
    found = [line for line in lines if type(line) is str and line.startswith(RECEIPT_LINE_PREFIX)]
    if not found:
        raise _refuse(ReceiptDefect.NO_RECEIPT)
    if len(found) > 1:
        raise _refuse(ReceiptDefect.DUPLICATE_RECEIPT)
    return found[0]


def decode_receipt_line(line: str) -> dict[str, Any]:
    """The receipt document of one line, or refuse."""
    if type(line) is not str or not line.startswith(RECEIPT_LINE_PREFIX):
        raise _refuse(ReceiptDefect.NO_RECEIPT)
    body = line[len(RECEIPT_LINE_PREFIX) :]
    try:
        encoded = body.encode("utf-8")
    except UnicodeEncodeError:
        # A line carrying a lone surrogate has no byte form at all.
        raise _refuse(ReceiptDefect.ENCODING_INVALID) from None
    if len(encoded) > MAX_RECEIPT_BYTES:
        raise _refuse(ReceiptDefect.TOO_LARGE)
    try:
        document = json.loads(body, object_pairs_hook=_no_duplicate_keys)
    except ReceiptError:
        raise
    except (ValueError, RecursionError):
        raise _refuse(ReceiptDefect.DOCUMENT_MALFORMED) from None
    if type(document) is not dict:
        raise _refuse(ReceiptDefect.DOCUMENT_MALFORMED)
    if contains_surrogate_text(document):
        raise _refuse(ReceiptDefect.ENCODING_INVALID)
    return document


def verify_receipt(document: object, *, expectation: ReceiptExpectation) -> VerifiedReceipt:
    """Every clause, in order: shape, digest, outcome consistency, then binding."""
    if type(expectation) is not ReceiptExpectation:
        raise _refuse(ReceiptDefect.FIELD_MALFORMED)
    if type(document) is not dict:
        raise _refuse(ReceiptDefect.DOCUMENT_MALFORMED)
    if not all(type(name) is str for name in document):
        raise _refuse(ReceiptDefect.DOCUMENT_MALFORMED)
    names = set(document)
    if names - _FIELDS:
        raise _refuse(ReceiptDefect.FIELD_UNKNOWN)
    if _FIELDS - names:
        raise _refuse(ReceiptDefect.FIELD_MISSING)
    # Every value must be JSON-shaped (no float, no foreign type) and free of lone
    # surrogates before a digest is computed over the document: the serializer's own
    # refusals must never be the answer to malformed evidence.
    if contains_surrogate_text(document):
        raise _refuse(ReceiptDefect.ENCODING_INVALID)
    if not is_json_shaped(document):
        raise _refuse(ReceiptDefect.FIELD_MALFORMED)
    if document["schema_version"] != RECEIPT_SCHEMA_VERSION:
        raise _refuse(ReceiptDefect.SCHEMA_VERSION_UNKNOWN)
    if document["contract_id"] != RECEIPT_CONTRACT_ID:
        raise _refuse(ReceiptDefect.CONTRACT_ID_UNKNOWN)
    declared = hex_digest(document["receipt_digest"])
    if declared is None:
        raise _refuse(ReceiptDefect.FIELD_MALFORMED)
    unsigned = {name: value for name, value in document.items() if name != "receipt_digest"}
    try:
        computed = sha256_hex(canonical_bytes(unsigned))
    except RecursionError:
        # A value nested past what the serializer can walk is malformed evidence.
        raise _refuse(ReceiptDefect.DOCUMENT_MALFORMED) from None
    if computed != declared:
        raise _refuse(ReceiptDefect.DIGEST_MISMATCH)

    # Exact type before membership, everywhere: an unhashable value in a membership
    # test is the interpreter's exception, not a closed refusal.
    raw_outcome = document["outcome"]
    if type(raw_outcome) is not str or raw_outcome not in {m.value for m in TaskOutcome}:
        raise _refuse(ReceiptDefect.OUTCOME_UNKNOWN)
    outcome = TaskOutcome(raw_outcome)
    raw_entry = document["entry"]
    entry: TaskEntry | None = None
    if outcome is TaskOutcome.REFUSED_ENTRY:
        # No entry was selected, so the receipt names none and invents no actor.
        if raw_entry is not None or document["actor"] is not None:
            raise _refuse(ReceiptDefect.EVIDENCE_CONTRADICTS_OUTCOME)
    else:
        if type(raw_entry) is not str or raw_entry not in {m.value for m in TaskEntry}:
            raise _refuse(ReceiptDefect.FIELD_MALFORMED)
        entry = TaskEntry(raw_entry)
        if document["actor"] != ENTRY_ACTOR[entry].value:
            raise _refuse(ReceiptDefect.FIELD_MALFORMED)
    if type(document["exit_code"]) is not int or document["exit_code"] != EXIT_STATUS[outcome]:
        raise _refuse(ReceiptDefect.EXIT_CODE_CONTRADICTS_OUTCOME)

    raw_runner = document["runner"]
    runner: RunnerOutcome | None = None
    if raw_runner is not None:
        if type(raw_runner) is not str or raw_runner not in {m.value for m in RunnerOutcome}:
            raise _refuse(ReceiptDefect.FIELD_MALFORMED)
        runner = RunnerOutcome(raw_runner)
    if outcome in PRE_BOOTSTRAP_OUTCOMES:
        if runner is not None:
            raise _refuse(ReceiptDefect.RUNNER_CONTRADICTS_OUTCOME)
    elif outcome in BOOTSTRAP_REFUSALS:
        if runner is None or BOOTSTRAP_OUTCOME.get(runner) is not outcome:
            raise _refuse(ReceiptDefect.RUNNER_CONTRADICTS_OUTCOME)
    elif runner is not RunnerOutcome.RELEASED:
        raise _refuse(ReceiptDefect.RUNNER_CONTRADICTS_OUTCOME)
    # A verification entry never completes a run, and only a verification entry verifies.
    if outcome is TaskOutcome.VERIFIED_BOOTSTRAP and entry not in VERIFICATION_ENTRIES:
        raise _refuse(ReceiptDefect.EVIDENCE_CONTRADICTS_OUTCOME)
    if outcome is TaskOutcome.COMPLETED and entry in VERIFICATION_ENTRIES:
        raise _refuse(ReceiptDefect.EVIDENCE_CONTRADICTS_OUTCOME)
    # A probe entry never completes a run and verifies no bootstrap; only a probe entry
    # reaches a probe outcome (proposed ADR-0048).
    if entry in PROBE_ENTRIES and outcome in (
        TaskOutcome.COMPLETED,
        TaskOutcome.VERIFIED_BOOTSTRAP,
    ):
        raise _refuse(ReceiptDefect.EVIDENCE_CONTRADICTS_OUTCOME)
    if outcome in PROBE_OUTCOMES and entry not in PROBE_ENTRIES:
        raise _refuse(ReceiptDefect.EVIDENCE_CONTRADICTS_OUTCOME)

    observed = document["counts_observed"]
    if type(observed) is not bool:
        raise _refuse(ReceiptDefect.FIELD_MALFORMED)
    if observed == (outcome is TaskOutcome.UNCLASSIFIED):
        raise _refuse(ReceiptDefect.COUNTS_CONTRADICT_OBSERVATION)
    raw_counts = document["counts"]
    counts: OperationCounts | None = None
    if observed:
        if raw_counts is None:
            raise _refuse(ReceiptDefect.COUNTS_CONTRADICT_OBSERVATION)
        # A present but malformed count block -- wrong shape, a missing or foreign
        # name, a non-integer or negative count -- is a malformed field, not an
        # observation contradiction: the task claimed a count it could not spell.
        if type(raw_counts) is not dict or set(raw_counts) != set(_COUNT_FIELDS):
            raise _refuse(ReceiptDefect.FIELD_MALFORMED)
        if any(type(value) is not int or value < 0 for value in raw_counts.values()):
            raise _refuse(ReceiptDefect.FIELD_MALFORMED)
        counts = OperationCounts(**raw_counts)
        if runner is not RunnerOutcome.RELEASED and counts.data_plane_operations != 0:
            raise _refuse(ReceiptDefect.COUNTS_CONTRADICT_OBSERVATION)
        # A verification task performs no data-plane operation, released or not; a
        # probe task counts its one operation in its observation, never here.
        if entry in VERIFICATION_ENTRIES and counts.data_plane_operations != 0:
            raise _refuse(ReceiptDefect.COUNTS_CONTRADICT_OBSERVATION)
        if entry in PROBE_ENTRIES and counts.data_plane_operations != 0:
            raise _refuse(ReceiptDefect.COUNTS_CONTRADICT_OBSERVATION)
    elif raw_counts is not None:
        raise _refuse(ReceiptDefect.COUNTS_CONTRADICT_OBSERVATION)

    raw_failures = document["cleanup_failures"]
    if type(raw_failures) is not list:
        raise _refuse(ReceiptDefect.FIELD_MALFORMED)
    failures: list[CleanupFailure] = []
    for raw in raw_failures:
        if type(raw) is not dict or set(raw) != {"stage", "failure"}:
            raise _refuse(ReceiptDefect.FIELD_MALFORMED)
        if type(raw["stage"]) is not str or raw["stage"] not in {m.value for m in CleanupStage}:
            raise _refuse(ReceiptDefect.FIELD_MALFORMED)
        if type(raw["failure"]) is not str or not raw["failure"]:
            raise _refuse(ReceiptDefect.FIELD_MALFORMED)
        failures.append(CleanupFailure(stage=CleanupStage(raw["stage"]), failure=raw["failure"]))

    unconfigured = outcome in (TaskOutcome.REFUSED_ENTRY, TaskOutcome.REFUSED_CONFIGURATION)
    for name, grammar in (
        ("code_commit", CODE_COMMIT_RE),
        ("configuration_digest", CONFIGURATION_DIGEST_RE),
    ):
        value = document[name]
        if value is None:
            if not unconfigured:
                raise _refuse(ReceiptDefect.FIELD_MISSING)
            continue
        if type(value) is not str or not grammar.fullmatch(value):
            raise _refuse(ReceiptDefect.FIELD_MALFORMED)

    # The two evidence blocks: each present exactly for the one outcome that produces
    # it, parsed under its own closed contract, and never anything but an observation.
    raw_probe = document["probe"]
    probe: ProbeObservation | None = None
    probed = entry is TaskEntry.BUILD_VERIFY and outcome is TaskOutcome.VERIFIED_BOOTSTRAP
    if (raw_probe is not None) != probed:
        raise _refuse(ReceiptDefect.EVIDENCE_CONTRADICTS_OUTCOME)
    if raw_probe is not None:
        try:
            probe = parse_probe_observation(raw_probe)
        except (TypeError, ValueError):
            raise _refuse(ReceiptDefect.FIELD_MALFORMED) from None
    raw_observation = document["schema_observation"]
    observation: SchemaObservation | None = None
    if raw_observation is not None:
        if not (entry is TaskEntry.BUILD and outcome is TaskOutcome.REFUSED_NORMALIZATION):
            raise _refuse(ReceiptDefect.EVIDENCE_CONTRADICTS_OUTCOME)
        try:
            observation = parse_schema_observation(raw_observation)
        except (TypeError, ValueError):
            raise _refuse(ReceiptDefect.FIELD_MALFORMED) from None

    raw_permission = document["permission"]
    permission: PermissionProbeObservation | None = None
    if (raw_permission is not None) != (outcome in PROBE_OUTCOMES):
        raise _refuse(ReceiptDefect.EVIDENCE_CONTRADICTS_OUTCOME)
    if raw_permission is not None:
        try:
            permission = parse_permission_probe_observation(raw_permission)
        except (TypeError, ValueError):
            raise _refuse(ReceiptDefect.FIELD_MALFORMED) from None
        held = outcome is TaskOutcome.PROBE_HELD
        if held != (permission.held_seconds > 0 and permission.operations == 0):
            raise _refuse(ReceiptDefect.EVIDENCE_CONTRADICTS_OUTCOME)
        if not held and permission.held_seconds != 0:
            raise _refuse(ReceiptDefect.EVIDENCE_CONTRADICTS_OUTCOME)
        if not held and permission.outcome.value != outcome.value.removeprefix("PROBE_"):
            raise _refuse(ReceiptDefect.EVIDENCE_CONTRADICTS_OUTCOME)

    bound = document["binding_digest"]
    released = runner is RunnerOutcome.RELEASED
    if released != (bound is not None):
        raise _refuse(ReceiptDefect.EVIDENCE_CONTRADICTS_OUTCOME)
    if bound is not None and hex_digest(bound) is None:
        raise _refuse(ReceiptDefect.FIELD_MALFORMED)

    # Binding to the launch record. The entry (where one was selected), the registered
    # code and configuration always; the binding digest when the bootstrap released. A
    # REFUSED_ENTRY receipt names no entry, and the collector binds it to the launch
    # through the launch record alone.
    if entry is not None and entry is not expectation.entry:
        raise _refuse(ReceiptDefect.ENTRY_MISMATCH)
    if document["configuration_digest"] not in (None, expectation.configuration_digest):
        raise _refuse(ReceiptDefect.CONFIGURATION_MISMATCH)
    if document["code_commit"] not in (None, expectation.code_commit):
        raise _refuse(ReceiptDefect.CONFIGURATION_MISMATCH)
    if bound is not None and bound != expectation.binding_digest:
        raise _refuse(ReceiptDefect.BINDING_MISMATCH)

    return VerifiedReceipt(
        entry=entry,
        outcome=outcome,
        runner=runner,
        counts=counts,
        cleanup_failures=tuple(failures),
        released=released,
        probe=probe,
        schema_observation=observation,
        permission=permission,
    )


def collect_and_verify(lines: Iterable[str], *, expectation: ReceiptExpectation) -> VerifiedReceipt:
    """The one receipt in ``lines``, decoded and verified against the launch record."""
    return verify_receipt(decode_receipt_line(collect_receipt_line(lines)), expectation=expectation)


# ---------------------------------------------------------------------------
# Ledger completion
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class LedgerCompletion:
    """What a verified receipt lets the launch tool write into the owner ledger."""

    outcome: str
    counts: OperationCounts | None

    def __post_init__(self) -> None:
        """A ledger outcome from the accepted vocabulary; counts only when observed."""
        if self.outcome not in LEDGER_OUTCOMES:
            raise ValueError("a ledger outcome must be one of the accepted members")
        if self.outcome == "COMPLETED" and self.counts is None:
            raise ValueError("a COMPLETED row requires observed counts")


def ledger_completion(receipt: VerifiedReceipt) -> LedgerCompletion | None:
    """The ledger row disposition a verified receipt establishes, or ``None``.

    ``COMPLETED`` requires the receipt's outcome to be ``COMPLETED`` **and** observed
    counts. Uncertain evidence -- an unknown locator or manifest state, unclassified
    accounting -- establishes no row: the owner reviews it. Nothing here turns a
    missing count into a measured zero.
    """
    if type(receipt) is not VerifiedReceipt:
        raise TypeError("receipt must be a VerifiedReceipt")
    outcome = receipt.ledger_outcome
    if outcome is None:
        return None
    if outcome == "COMPLETED" and receipt.counts is None:
        return None
    return LedgerCompletion(outcome=outcome, counts=receipt.counts)


__all__ = [
    "BOOTSTRAP_REFUSALS",
    "LEDGER_OUTCOME_OF",
    "MAX_RECEIPT_BYTES",
    "PRE_BOOTSTRAP_OUTCOMES",
    "RECEIPT_CONTRACT_ID",
    "RECEIPT_LINE_PREFIX",
    "RECEIPT_SCHEMA_VERSION",
    "LedgerCompletion",
    "ReceiptDefect",
    "ReceiptError",
    "ReceiptExpectation",
    "VerifiedReceipt",
    "binding_digest",
    "collect_and_verify",
    "collect_receipt_line",
    "decode_receipt_line",
    "ledger_completion",
    "receipt_document",
    "receipt_line",
    "verify_receipt",
]
