"""The compiled configuration an image carries beside its code (ADR-0044 §2).

**What it is.** One closed JSON document, generated deterministically at the image gate
from the repository's constants and the owner's Terraform-gate values, copied into the
image at a fixed path and read by the task entrypoint at start. It carries what the
accepted entrypoint composition (ADR-0043) needs beyond the code and could not obtain
from a binding, an input, a release or the environment: for the acquisition entry the
secret **name** (never a value, never an ARN with an account) and the compiled origin
address set; for the build entry the whole pinned build configuration. Its SHA-256 over
the exact file bytes is the ``configuration_digest`` of the accepted ``CompiledTask``,
recorded at generation and bound by the launch tool into the placement release, so a
task whose file differs from what was registered refuses at the barrier.

**What it deliberately cannot do.** It cannot carry the image's own digest or the
task-definition revision -- neither exists when the file is generated -- and it does not
try: those are attested by the release. It carries no credential, no account id, no
bucket name and no licensed data; a document that carries a field outside the closed
set is refused, so nothing can be smuggled in beside the expected values.

**Validation is total and value-free.** Every field is held to a grammar; the build
configuration is parsed back into the accepted :class:`BuildConfiguration` and must
reproduce the digest it declares; the derivation-version constants it pins must equal
the ones this code implements. A refusal names a closed defect and never a value.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.ingest.sharadar.datasets import SharadarDataset
from kalpamani.data.production.sharadar.availability import (
    ACTION_SELECTION_VERSION,
    AvailabilityEvidence,
    EvidenceKind,
    VersionEvidence,
)
from kalpamani.data.production.sharadar.build_manifest import (
    BuildConfiguration,
    BuildConfigurationError,
)
from kalpamani.data.production.sharadar.documents import contains_surrogate_text
from kalpamani.data.production.sharadar.entry import (
    ENTRY_ACTOR,
    PROBE_ENTRIES,
    EntryConfiguration,
    TaskEntry,
    entry_family,
)
from kalpamani.data.production.sharadar.gold import (
    ADJUSTMENT_CONVENTION,
    ADJUSTMENT_DERIVATION_VERSION,
    ADJUSTMENT_POLICY,
)
from kalpamani.data.production.sharadar.metadata import CompiledTask
from kalpamani.data.production.sharadar.metadata_grammar import CODE_COMMIT_RE
from kalpamani.data.production.sharadar.pagination import PAGINATION_POLICY_VERSION
from kalpamani.data.production.sharadar.plan import pagination_targets_document
from kalpamani.data.production.sharadar.processing import SOURCE_SCHEMA_VERSION
from kalpamani.data.production.sharadar.sessions import Session as TradingSession
from kalpamani.data.production.sharadar.sessions import SessionCalendar
from kalpamani.data.production.sharadar.silver import (
    ACTIONS_IDENTITY_VERSION,
    SILVER_NORMALIZATION_VERSION,
    AcceptedSchemas,
)
from kalpamani.data.production.sharadar.task_clients import compiled_origin_addresses
from kalpamani.data.production.sharadar.universe import UNIVERSE_RULE_VERSION, UniverseRule

COMPILED_CONFIGURATION_CONTRACT_ID: Final = "kalpamani-compiled-configuration/v1"
COMPILED_CONFIGURATION_SCHEMA_VERSION: Final = 1
#: Where the image carries the file. Fixed; the entrypoint accepts no other path.
COMPILED_CONFIGURATION_PATH: Final = "/etc/kalpamani/compiled-configuration.json"
#: A ceiling on the file: the build configuration is the largest part, and it is small.
MAX_COMPILED_CONFIGURATION_BYTES: Final = 256 * 1024

_COMMON_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "entry",
        "actor",
        "family",
        "code_commit",
        "code_tree",
        "generated_at",
    }
)
#: The acquisition entry's file also carries the pagination-v2 deployment targets
#: (ADR-0053 §13.2), pinned to the plan's constants at parse time.
_ACQUISITION_FIELDS: Final[frozenset[str]] = _COMMON_FIELDS | {
    "secret_name",
    "origin_addresses",
    "pagination_targets",
}
_BUILD_FIELDS: Final[frozenset[str]] = _COMMON_FIELDS | {"build_configuration"}
#: A verification entry's file (proposed ADR-0045): the origin address set and nothing
#: actor-specific beyond it -- no secret name, no build configuration -- so a
#: verification image carries no capability its entry must not hold.
_VERIFICATION_FIELDS: Final[frozenset[str]] = _COMMON_FIELDS | {"origin_addresses"}
#: A permission-probe entry's file (ADR-0048): the common fields and nothing
#: else -- no secret name, no origin address set, no build configuration. The subcell a
#: probe issues comes from its input, never from the image.
_PROBE_FIELDS: Final[frozenset[str]] = _COMMON_FIELDS
ENTRY_FIELDS: Final[dict[TaskEntry, frozenset[str]]] = {
    TaskEntry.ACQUISITION: _ACQUISITION_FIELDS,
    TaskEntry.BUILD: _BUILD_FIELDS,
    TaskEntry.ACQUISITION_VERIFY: _VERIFICATION_FIELDS,
    TaskEntry.BUILD_VERIFY: _VERIFICATION_FIELDS,
    TaskEntry.ACQUISITION_PROBE: _PROBE_FIELDS,
    TaskEntry.BUILD_PROBE: _PROBE_FIELDS,
}
_BUILD_CONFIGURATION_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "accepted_schemas",
        "calendar",
        "evidence",
        "universe_rule",
        "decision_sessions",
        "as_of",
        "commit",
        "jump_ratio",
        "reconciliation_tolerance",
        "adjustment_policy",
        "adjustment_convention",
        "adjustment_derivation_version",
        "action_selection_version",
        "silver_normalization_version",
        "source_schema_version",
        "pagination_policy_version",
        "actions_identity_version",
    }
)

#: A Secrets Manager secret *name*: the documented name grammar, and never an ARN --
#: an ARN carries an account id, and the image carries none.
_SECRET_NAME_CHARS: Final = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/_+=.@-"
)


class CompiledConfigurationDefect(StrEnum):
    """Why a compiled configuration was refused. Closed; carries no value."""

    UNREADABLE = "UNREADABLE"
    EMPTY = "EMPTY"
    TOO_LARGE = "TOO_LARGE"
    ENCODING_INVALID = "ENCODING_INVALID"
    DOCUMENT_MALFORMED = "DOCUMENT_MALFORMED"
    DUPLICATE_KEY = "DUPLICATE_KEY"
    SCHEMA_VERSION_UNKNOWN = "SCHEMA_VERSION_UNKNOWN"
    CONTRACT_ID_UNKNOWN = "CONTRACT_ID_UNKNOWN"
    FIELD_UNKNOWN = "FIELD_UNKNOWN"
    FIELD_MISSING = "FIELD_MISSING"
    FIELD_MALFORMED = "FIELD_MALFORMED"
    ENTRY_UNKNOWN = "ENTRY_UNKNOWN"
    ACTOR_MISMATCH = "ACTOR_MISMATCH"
    SECRET_NAME_MALFORMED = "SECRET_NAME_MALFORMED"  # noqa: S105 - a defect token
    ORIGIN_ADDRESSES_MALFORMED = "ORIGIN_ADDRESSES_MALFORMED"
    BUILD_CONFIGURATION_MALFORMED = "BUILD_CONFIGURATION_MALFORMED"
    DERIVATION_VERSION_MISMATCH = "DERIVATION_VERSION_MISMATCH"
    PAGINATION_TARGETS_MISMATCH = "PAGINATION_TARGETS_MISMATCH"


class CompiledConfigurationError(Exception):
    """A refusal built from one closed member and nothing else."""

    __slots__ = ("defect",)

    def __init__(self, defect: CompiledConfigurationDefect) -> None:
        """Carry the defect."""
        if type(defect) is not CompiledConfigurationDefect:
            raise TypeError("defect must be an exact CompiledConfigurationDefect member")
        self.defect = defect
        super().__init__(f"compiled configuration: {defect.value}")


def _refuse(defect: CompiledConfigurationDefect) -> CompiledConfigurationError:
    return CompiledConfigurationError(defect)


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise _refuse(CompiledConfigurationDefect.DUPLICATE_KEY)
        seen[key] = value
    return seen


def decode_compiled_configuration(raw: object) -> dict[str, Any]:
    """The closed object of one compiled configuration file, refused above the ceiling."""
    if type(raw) is not bytes:
        raise _refuse(CompiledConfigurationDefect.UNREADABLE)
    if not raw:
        raise _refuse(CompiledConfigurationDefect.EMPTY)
    if len(raw) > MAX_COMPILED_CONFIGURATION_BYTES:
        raise _refuse(CompiledConfigurationDefect.TOO_LARGE)
    if raw.startswith(b"\xef\xbb\xbf"):
        raise _refuse(CompiledConfigurationDefect.ENCODING_INVALID)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _refuse(CompiledConfigurationDefect.ENCODING_INVALID) from None
    try:
        document = json.loads(text, object_pairs_hook=_no_duplicate_keys)
    except CompiledConfigurationError:
        raise
    except ValueError:
        # ``json.JSONDecodeError`` and the decoder's own value refusals: malformed text.
        raise _refuse(CompiledConfigurationDefect.DOCUMENT_MALFORMED) from None
    except RecursionError:
        raise _refuse(CompiledConfigurationDefect.DOCUMENT_MALFORMED) from None
    if type(document) is not dict:
        raise _refuse(CompiledConfigurationDefect.DOCUMENT_MALFORMED)
    if contains_surrogate_text(document):
        # A lone surrogate has no UTF-8 form: the file could never round-trip.
        raise _refuse(CompiledConfigurationDefect.ENCODING_INVALID)
    return document


def configuration_digest_of(raw: bytes) -> str:
    """The SHA-256 over the exact file bytes: the accepted ``configuration_digest``."""
    if type(raw) is not bytes:
        raise _refuse(CompiledConfigurationDefect.UNREADABLE)
    return sha256_hex(raw)


# ---------------------------------------------------------------------------
# The build configuration, parsed back from its own document
# ---------------------------------------------------------------------------


def _exact_str(value: object) -> str:
    if type(value) is not str or not value:
        raise _refuse(CompiledConfigurationDefect.BUILD_CONFIGURATION_MALFORMED)
    return value


def _instant(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(_exact_str(value))
    except ValueError:
        raise _refuse(CompiledConfigurationDefect.BUILD_CONFIGURATION_MALFORMED) from None
    if parsed.tzinfo is None:
        raise _refuse(CompiledConfigurationDefect.BUILD_CONFIGURATION_MALFORMED)
    return parsed


def _day(value: object) -> date:
    try:
        return date.fromisoformat(_exact_str(value))
    except ValueError:
        raise _refuse(CompiledConfigurationDefect.BUILD_CONFIGURATION_MALFORMED) from None


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(_exact_str(value))
    except InvalidOperation:
        raise _refuse(CompiledConfigurationDefect.BUILD_CONFIGURATION_MALFORMED) from None


def _closed(value: object, fields: frozenset[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        raise _refuse(CompiledConfigurationDefect.BUILD_CONFIGURATION_MALFORMED)
    return value


def parse_build_configuration(document: object) -> BuildConfiguration:
    """The accepted :class:`BuildConfiguration` from its own ``document()`` shape.

    Round-trips exactly: ``parse_build_configuration(c.document()).document() ==
    c.document()``. The derivation-version constants the document pins must equal the
    ones this code implements; a document pinned to another derivation cannot run here.
    """
    payload = _closed(document, _BUILD_CONFIGURATION_FIELDS)
    pinned = {
        "adjustment_policy": ADJUSTMENT_POLICY.value,
        "adjustment_convention": ADJUSTMENT_CONVENTION.value,
        "adjustment_derivation_version": ADJUSTMENT_DERIVATION_VERSION,
        "action_selection_version": ACTION_SELECTION_VERSION,
        "silver_normalization_version": SILVER_NORMALIZATION_VERSION,
        "source_schema_version": SOURCE_SCHEMA_VERSION,
        "pagination_policy_version": PAGINATION_POLICY_VERSION,
        "actions_identity_version": ACTIONS_IDENTITY_VERSION,
    }
    for name, expected in pinned.items():
        if payload[name] != expected:
            raise _refuse(CompiledConfigurationDefect.DERIVATION_VERSION_MISMATCH)

    schemas = _closed(payload["accepted_schemas"], frozenset({"version", "digests"}))
    digests = schemas["digests"]
    if type(digests) is not dict:
        raise _refuse(CompiledConfigurationDefect.BUILD_CONFIGURATION_MALFORMED)
    known = {member.value for member in SharadarDataset}
    accepted: dict[str, frozenset[str]] = {}
    for dataset, values in digests.items():
        if dataset not in known or type(values) is not list:
            raise _refuse(CompiledConfigurationDefect.BUILD_CONFIGURATION_MALFORMED)
        accepted[dataset] = frozenset(_exact_str(v) for v in values)

    calendar = _closed(payload["calendar"], frozenset({"version", "sessions"}))
    if type(calendar["sessions"]) is not list:
        raise _refuse(CompiledConfigurationDefect.BUILD_CONFIGURATION_MALFORMED)
    sessions: list[TradingSession] = []
    for raw_session in calendar["sessions"]:
        session = _closed(raw_session, frozenset({"session_date", "open_at"}))
        # The accepted value contract refuses a session that opens before its own
        # date with its own exception; here that is one more malformed document.
        try:
            sessions.append(
                TradingSession(
                    session_date=_day(session["session_date"]),
                    open_at=_instant(session["open_at"]),
                )
            )
        except (TypeError, ValueError):
            raise _refuse(CompiledConfigurationDefect.BUILD_CONFIGURATION_MALFORMED) from None

    evidence = _closed(payload["evidence"], frozenset({"version", "items"}))
    if type(evidence["items"]) is not list:
        raise _refuse(CompiledConfigurationDefect.BUILD_CONFIGURATION_MALFORMED)
    items: list[VersionEvidence] = []
    item_fields = frozenset(
        {"kind", "dataset", "row_key", "content_sha256", "instant", "evidence_digest"}
    )
    for raw in evidence["items"]:
        item = _closed(raw, item_fields)
        try:
            kind = EvidenceKind(_exact_str(item["kind"]))
        except ValueError:
            raise _refuse(CompiledConfigurationDefect.BUILD_CONFIGURATION_MALFORMED) from None
        if type(item["row_key"]) is not list:
            raise _refuse(CompiledConfigurationDefect.BUILD_CONFIGURATION_MALFORMED)
        # The accepted evidence contract refuses a short digest or a naive instant
        # with its own exception; here that is one more malformed document.
        try:
            items.append(
                VersionEvidence(
                    kind=kind,
                    dataset=_exact_str(item["dataset"]),
                    row_key=tuple(_exact_str(k) for k in item["row_key"]),
                    content_sha256=(
                        None
                        if item["content_sha256"] is None
                        else _exact_str(item["content_sha256"])
                    ),
                    instant=None if item["instant"] is None else _instant(item["instant"]),
                    evidence_digest=_exact_str(item["evidence_digest"]),
                )
            )
        except (TypeError, ValueError):
            raise _refuse(CompiledConfigurationDefect.BUILD_CONFIGURATION_MALFORMED) from None

    rule_document = _closed(
        payload["universe_rule"],
        frozenset(
            {
                "universe_rule_version",
                "decision_margin_seconds",
                "history_sessions",
                "addv_window_sessions",
                "price_floor",
                "addv_floor",
                "eligible_exchanges",
                "common_stock_categories",
            }
        ),
    )
    if rule_document["universe_rule_version"] != UNIVERSE_RULE_VERSION:
        raise _refuse(CompiledConfigurationDefect.DERIVATION_VERSION_MISMATCH)
    for name in ("decision_margin_seconds", "history_sessions", "addv_window_sessions"):
        if type(rule_document[name]) is not int or rule_document[name] < 0:
            raise _refuse(CompiledConfigurationDefect.BUILD_CONFIGURATION_MALFORMED)
    for name in ("eligible_exchanges", "common_stock_categories"):
        if type(rule_document[name]) is not list:
            raise _refuse(CompiledConfigurationDefect.BUILD_CONFIGURATION_MALFORMED)
    if type(payload["decision_sessions"]) is not list:
        raise _refuse(CompiledConfigurationDefect.BUILD_CONFIGURATION_MALFORMED)
    try:
        return BuildConfiguration(
            schemas=AcceptedSchemas(version=_exact_str(schemas["version"]), digests=accepted),
            calendar=SessionCalendar(
                version=_exact_str(calendar["version"]), sessions=tuple(sessions)
            ),
            evidence=AvailabilityEvidence(
                version=_exact_str(evidence["version"]), items=tuple(items)
            ),
            rule=UniverseRule(
                version=UNIVERSE_RULE_VERSION,
                decision_margin=timedelta(seconds=rule_document["decision_margin_seconds"]),
                history_sessions=rule_document["history_sessions"],
                addv_window_sessions=rule_document["addv_window_sessions"],
                price_floor=_decimal(rule_document["price_floor"]),
                addv_floor=_decimal(rule_document["addv_floor"]),
                eligible_exchanges=frozenset(
                    _exact_str(v) for v in rule_document["eligible_exchanges"]
                ),
                common_stock_categories=frozenset(
                    _exact_str(v) for v in rule_document["common_stock_categories"]
                ),
            ),
            decision_sessions=tuple(_day(d) for d in payload["decision_sessions"]),
            as_of=_instant(payload["as_of"]),
            commit=_exact_str(payload["commit"]),
            jump_ratio=_decimal(payload["jump_ratio"]),
            reconciliation_tolerance=_decimal(payload["reconciliation_tolerance"]),
        )
    except (BuildConfigurationError, TypeError, ValueError):
        raise _refuse(CompiledConfigurationDefect.BUILD_CONFIGURATION_MALFORMED) from None


# ---------------------------------------------------------------------------
# The compiled configuration document
# ---------------------------------------------------------------------------


def secret_name_refusal(value: object) -> str | None:
    """Why ``value`` is not a usable secret name, or ``None``. Never accepts an ARN."""
    if type(value) is not str or not 1 <= len(value) <= 512:
        return "the secret name is not a string of the documented length"
    if value.startswith("arn:"):
        return "the secret name must be a name, not an ARN"
    if any(character not in _SECRET_NAME_CHARS for character in value):
        return "the secret name carries a character outside the documented grammar"
    return None


def parse_compiled_configuration(raw: bytes) -> tuple[EntryConfiguration, str]:
    """The entry configuration a compiled file carries, and the file's digest, or refuse.

    The digest is over the exact bytes handed in -- the bytes the image carries -- and
    becomes the accepted ``CompiledTask.configuration_digest`` the release must match.
    """
    digest = configuration_digest_of(raw)
    document = decode_compiled_configuration(raw)
    names = set(document)
    entry_value = document.get("entry")
    # Exact type before membership: a list or an object is unhashable and would turn a
    # closed refusal into the interpreter's own exception.
    if type(entry_value) is not str or entry_value not in {member.value for member in TaskEntry}:
        raise _refuse(CompiledConfigurationDefect.ENTRY_UNKNOWN)
    entry = TaskEntry(entry_value)
    fields = ENTRY_FIELDS[entry]
    if names - fields:
        raise _refuse(CompiledConfigurationDefect.FIELD_UNKNOWN)
    if fields - names:
        raise _refuse(CompiledConfigurationDefect.FIELD_MISSING)
    if document["schema_version"] != COMPILED_CONFIGURATION_SCHEMA_VERSION:
        raise _refuse(CompiledConfigurationDefect.SCHEMA_VERSION_UNKNOWN)
    if document["contract_id"] != COMPILED_CONFIGURATION_CONTRACT_ID:
        raise _refuse(CompiledConfigurationDefect.CONTRACT_ID_UNKNOWN)
    actor = ENTRY_ACTOR[entry]
    if document["actor"] != actor.value:
        raise _refuse(CompiledConfigurationDefect.ACTOR_MISMATCH)
    if document["family"] != entry_family(entry):
        raise _refuse(CompiledConfigurationDefect.ACTOR_MISMATCH)
    for name in ("code_commit", "code_tree"):
        value = document[name]
        if type(value) is not str or not CODE_COMMIT_RE.fullmatch(value):
            raise _refuse(CompiledConfigurationDefect.FIELD_MALFORMED)
    generated_at = document["generated_at"]
    try:
        if type(generated_at) is not str or datetime.fromisoformat(generated_at).tzinfo is None:
            raise ValueError
    except ValueError:
        raise _refuse(CompiledConfigurationDefect.FIELD_MALFORMED) from None

    compiled = CompiledTask(
        actor=actor,
        family=document["family"],
        code_commit=document["code_commit"],
        configuration_digest=digest,
    )
    if entry is TaskEntry.BUILD:
        build = parse_build_configuration(document["build_configuration"])
        configuration = EntryConfiguration(
            entry=entry, compiled=compiled, build_configuration=build
        )
        return configuration, digest
    if entry in PROBE_ENTRIES:
        return EntryConfiguration(entry=entry, compiled=compiled), digest
    addresses = document["origin_addresses"]
    if type(addresses) is not list or not addresses:
        raise _refuse(CompiledConfigurationDefect.ORIGIN_ADDRESSES_MALFORMED)
    try:
        origin = compiled_origin_addresses(addresses)
    except ValueError:
        raise _refuse(CompiledConfigurationDefect.ORIGIN_ADDRESSES_MALFORMED) from None
    if entry is TaskEntry.ACQUISITION:
        if secret_name_refusal(document["secret_name"]) is not None:
            raise _refuse(CompiledConfigurationDefect.SECRET_NAME_MALFORMED)
        # The deployment targets the image was generated for must be the ones this
        # code compiles; a file naming other limits, ceilings or memory cannot run here.
        if document["pagination_targets"] != pagination_targets_document():
            raise _refuse(CompiledConfigurationDefect.PAGINATION_TARGETS_MISMATCH)
        configuration = EntryConfiguration(
            entry=entry,
            compiled=compiled,
            secret_identifier=document["secret_name"],
            origin_addresses=origin,
        )
    else:
        configuration = EntryConfiguration(entry=entry, compiled=compiled, origin_addresses=origin)
    return configuration, digest


def build_compiled_configuration(
    *,
    entry: TaskEntry,
    code_commit: str,
    code_tree: str,
    generated_at: datetime,
    secret_name: str | None = None,
    origin_addresses: list[str] | None = None,
    build_configuration: BuildConfiguration | None = None,
) -> bytes:
    """The deterministic file bytes the image gate generates, validated before return.

    Canonical serialization, so the same inputs always produce the same bytes and the
    same digest. The result is parsed back through :func:`parse_compiled_configuration`
    before it is returned, so a generator cannot emit a file the entrypoint would refuse.
    """
    actor = ENTRY_ACTOR[entry]
    document: dict[str, Any] = {
        "schema_version": COMPILED_CONFIGURATION_SCHEMA_VERSION,
        "contract_id": COMPILED_CONFIGURATION_CONTRACT_ID,
        "entry": entry.value,
        "actor": actor.value,
        "family": entry_family(entry),
        "code_commit": code_commit,
        "code_tree": code_tree,
        "generated_at": generated_at.isoformat() if type(generated_at) is datetime else "",
    }
    if entry is TaskEntry.BUILD:
        document["build_configuration"] = (
            build_configuration.document() if build_configuration is not None else None
        )
    elif entry in PROBE_ENTRIES:
        pass  # the common fields and nothing else
    else:
        document["origin_addresses"] = (
            sorted(compiled_origin_addresses(origin_addresses)) if origin_addresses else []
        )
        if entry is TaskEntry.ACQUISITION:
            document["secret_name"] = secret_name
            document["pagination_targets"] = pagination_targets_document()
    raw = canonical_bytes(document)
    parse_compiled_configuration(raw)
    return raw


__all__ = [
    "COMPILED_CONFIGURATION_CONTRACT_ID",
    "COMPILED_CONFIGURATION_PATH",
    "COMPILED_CONFIGURATION_SCHEMA_VERSION",
    "ENTRY_FIELDS",
    "MAX_COMPILED_CONFIGURATION_BYTES",
    "CompiledConfigurationDefect",
    "CompiledConfigurationError",
    "build_compiled_configuration",
    "configuration_digest_of",
    "decode_compiled_configuration",
    "parse_build_configuration",
    "parse_compiled_configuration",
    "secret_name_refusal",
]
