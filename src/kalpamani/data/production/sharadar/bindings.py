"""The two production runtime bindings, and the two deliveries (ADR-0036 §2.5).

**One loader, two deliveries.** A human actor reads an ACL-protected private file
under the ADR-0023 trust boundary, through the accepted qualification reader and
its containment, ownership, size and swap rules. A task has no private root and no
Windows ACL, so it reads its binding from a per-actor SSM ``SecureString``
parameter through an injected reader. Both deliveries hand the same decoded
document to the same :func:`parse_production_runtime_binding`, so the schema,
kind, contract, partition, region, profile field, account grammar, bucket grammar
and provenance clauses are enforced once.

**The field sets differ by exactly the profile field name**, so neither actor's
binding loads as the other's, and neither loads as a qualification binding: the
kinds and contracts are distinct literals, matched exactly.

**Loading is not identity proof.** The binding is *input* to the identity gate
(:mod:`identity`): the gate compares the authenticated account to
``target_account_id`` and the authenticated role name to the actor's compiled
role name. A forged binding fails that comparison; it cannot steer it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol

from kalpamani.data.production.sharadar.vocabulary import (
    EXPECTED_PARTITION,
    EXPECTED_REGION,
    MAX_BINDING_PARAMETER_BYTES,
    ProductionActor,
    constants_for,
)
from kalpamani.data.qualify.sharadar.runtime_binding import (
    MAX_RUNTIME_BINDING_BYTES,
    FileSecurity,
    RuntimeBindingDefect,
    RuntimeBindingError,
    private_root,
    read_private_document,
    windows_file_security,
)

#: A twelve-digit AWS account number, and nothing else.
_ACCOUNT_ID: Final = re.compile(r"^[0-9]{12}$")

#: An S3 bucket name under the current naming rules, as the qualification loader
#: spells it.
_BUCKET_NAME: Final = re.compile(r"^[a-z0-9][a-z0-9.\-]{1,61}[a-z0-9]$")

#: A Git object name and a SHA-256 digest: lowercase hex, fixed length.
_GIT_OBJECT: Final = re.compile(r"^[0-9a-f]{40}$")
_SHA256_HEX: Final = re.compile(r"^[0-9a-f]{64}$")

#: The one schema version either binding admits. Exact, not a minimum.
BINDING_SCHEMA_VERSION: Final = 1

#: The fields every production binding carries, before the actor's profile field
#: is added. An allowlist: an unanticipated field is refused rather than ignored.
_COMMON_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "binding_kind",
        "contract_id",
        "aws_partition",
        "aws_region",
        "target_account_id",
        "licensed_bucket_name",
        "provenance",
    }
)

#: The provenance block. Shape-checked and never returned, as in ADR-0023.
_PROVENANCE_FIELDS: Final[frozenset[str]] = frozenset(
    {"implementation_commit", "implementation_tree", "environment_binding_sha256"}
)


def _refuse(defect: RuntimeBindingDefect) -> RuntimeBindingError:
    return RuntimeBindingError(defect)


def binding_fields(actor: ProductionActor) -> frozenset[str]:
    """The exact top-level field set of ``actor``'s binding."""
    return _COMMON_FIELDS | {constants_for(actor).profile_field}


@dataclass(frozen=True, slots=True, kw_only=True)
class ProductionRuntimeBinding:
    """What a validated production binding supplies to the run.

    The account is returned because the identity gate compares against it; the
    bucket because every key is published into it. The provenance block is
    validated and **not** returned, on the ADR-0023 rule.
    """

    actor: ProductionActor
    target_account_id: str
    licensed_bucket_name: str
    partition: str
    region: str
    profile: str

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing."""
        raise TypeError("ProductionRuntimeBinding may not be subclassed")

    def __repr__(self) -> str:
        """The actor only. **Never the account, and never the bucket.**"""
        return f"ProductionRuntimeBinding(actor={self.actor.value!r})"


def _exact_string(container: dict[str, Any], field: str) -> str:
    value = container[field]
    if type(value) is not str:
        raise _refuse(RuntimeBindingDefect.FIELD_MALFORMED) from None
    return value


def _validate_provenance(raw: object) -> None:
    if type(raw) is not dict:
        raise _refuse(RuntimeBindingDefect.PROVENANCE_MALFORMED) from None
    names = set(raw)
    if names - _PROVENANCE_FIELDS:
        raise _refuse(RuntimeBindingDefect.FIELD_UNKNOWN) from None
    if _PROVENANCE_FIELDS - names:
        raise _refuse(RuntimeBindingDefect.FIELD_MISSING) from None
    for field, grammar in (
        ("implementation_commit", _GIT_OBJECT),
        ("implementation_tree", _GIT_OBJECT),
        ("environment_binding_sha256", _SHA256_HEX),
    ):
        value = raw[field]
        if type(value) is not str or not grammar.match(value):
            raise _refuse(RuntimeBindingDefect.PROVENANCE_MALFORMED) from None


def parse_production_runtime_binding(
    document: object, *, actor: ProductionActor
) -> ProductionRuntimeBinding:
    """Validate an already-decoded binding document for ``actor``. **Reads nothing.**

    Every clause is a refusal naming a rule, and the order is fixed: shape, then
    schema, kind and contract, then partition and region, then the actor's own
    profile field, then the account and bucket grammars, then provenance. The
    other actor's document refuses at the field-set clause, and a qualification
    binding refuses there as well.

    Raises:
        RuntimeBindingError: one closed :class:`RuntimeBindingDefect`. **No refusal
            names the account, the bucket, a digest or any fragment of the document.**
    """
    constants = constants_for(actor)
    if type(document) is not dict:
        raise _refuse(RuntimeBindingDefect.DOCUMENT_MALFORMED) from None
    fields = binding_fields(actor)
    names = set(document)
    if names - fields:
        raise _refuse(RuntimeBindingDefect.FIELD_UNKNOWN) from None
    if fields - names:
        raise _refuse(RuntimeBindingDefect.FIELD_MISSING) from None

    version = document["schema_version"]
    if type(version) is not int:
        raise _refuse(RuntimeBindingDefect.FIELD_MALFORMED) from None
    if version != BINDING_SCHEMA_VERSION:
        raise _refuse(RuntimeBindingDefect.SCHEMA_VERSION_UNKNOWN) from None
    if _exact_string(document, "binding_kind") != constants.binding_kind:
        raise _refuse(RuntimeBindingDefect.BINDING_KIND_UNKNOWN) from None
    if _exact_string(document, "contract_id") != constants.binding_contract_id:
        raise _refuse(RuntimeBindingDefect.CONTRACT_ID_UNKNOWN) from None
    if _exact_string(document, "aws_partition") != EXPECTED_PARTITION:
        raise _refuse(RuntimeBindingDefect.PARTITION_UNEXPECTED) from None
    if _exact_string(document, "aws_region") != EXPECTED_REGION:
        raise _refuse(RuntimeBindingDefect.REGION_UNEXPECTED) from None
    if _exact_string(document, constants.profile_field) != constants.profile:
        raise _refuse(RuntimeBindingDefect.PROFILE_UNEXPECTED) from None

    account = _exact_string(document, "target_account_id")
    if not _ACCOUNT_ID.match(account):
        raise _refuse(RuntimeBindingDefect.ACCOUNT_MALFORMED) from None
    bucket = _exact_string(document, "licensed_bucket_name")
    if not _BUCKET_NAME.match(bucket):
        raise _refuse(RuntimeBindingDefect.BUCKET_NAME_MALFORMED) from None
    _validate_provenance(document["provenance"])

    return ProductionRuntimeBinding(
        actor=actor,
        target_account_id=account,
        licensed_bucket_name=bucket,
        partition=EXPECTED_PARTITION,
        region=EXPECTED_REGION,
        profile=constants.profile,
    )


# ---------------------------------------------------------------------------
# Delivery one: the human's private file
# ---------------------------------------------------------------------------


def human_binding_path(actor: ProductionActor, *, environment: Callable[[str], str | None]) -> str:
    """The binding path, from ``actor``'s one fixed environment-variable name.

    ``environment`` is injected -- a lookup by *name* -- so this module reads no
    process environment on import and a test supplies its own. The production
    caller passes ``os.environ.get``.

    Raises:
        RuntimeBindingError: ``ENVIRONMENT_UNSET`` if the variable is absent or
            blank. **There is no default path**, no scan and no fallback.
    """
    value = environment(constants_for(actor).binding_env_var)
    if type(value) is not str or not value.strip():
        raise _refuse(RuntimeBindingDefect.ENVIRONMENT_UNSET) from None
    return value


def load_human_runtime_binding(
    actor: ProductionActor,
    *,
    environment: Callable[[str], str | None],
    root_source: Callable[[], Path] | None = None,
    security_of: Callable[[Path], FileSecurity] | None = None,
) -> ProductionRuntimeBinding:
    """Read and validate the private binding file the environment selects.

    Delegates the read to the accepted qualification reader, so containment
    beneath the private root, the regular-file and no-link rules, owner-only
    exclusive ACL, the size ceiling, the swap check and strict decoding are the
    same functions rather than a restatement. ``root_source`` and ``security_of``
    are injection seams for tests only and default to the production sources when
    the call happens.

    Raises:
        RuntimeBindingError: one closed defect; never a path or a value.
    """
    raw_path = human_binding_path(actor, environment=environment)
    root = (private_root if root_source is None else root_source)()
    if not isinstance(root, Path) or not root.is_absolute():
        raise _refuse(RuntimeBindingDefect.PRIVATE_ROOT_UNRESOLVED) from None
    document = read_private_document(
        raw_path,
        root,
        windows_file_security if security_of is None else security_of,
        MAX_RUNTIME_BINDING_BYTES,
    )
    return parse_production_runtime_binding(document, actor=actor)


# ---------------------------------------------------------------------------
# Delivery two: the task's SecureString parameter
# ---------------------------------------------------------------------------


class ParameterReader(Protocol):
    """One operation: the decrypted bytes of one named parameter.

    Satisfied by the SSM adapter in :mod:`adapters` and by any synthetic reader.
    There is no listing, no history and no write in the shape.
    """

    def read_parameter(self, name: str) -> bytes:
        """The parameter's value, as UTF-8 bytes. Raises on any failure."""
        ...


def decode_parameter_document(raw: object, *, max_bytes: int) -> object:
    """Decode one parameter value under the private-artifact rules. **Reads nothing.**

    The same three rules the file decoder applies -- no byte-order mark, strict
    UTF-8, no duplicate key -- with the size ceiling checked **before** decoding,
    so an oversize value is never parsed.

    Raises:
        RuntimeBindingError: ``FILE_UNREADABLE`` for a non-``bytes`` value,
            ``FILE_EMPTY``, ``FILE_TOO_LARGE``, ``ENCODING_INVALID``,
            ``DOCUMENT_MALFORMED`` or ``DUPLICATE_KEY``.
    """
    if type(raw) is not bytes:
        raise _refuse(RuntimeBindingDefect.FILE_UNREADABLE) from None
    if not raw:
        raise _refuse(RuntimeBindingDefect.FILE_EMPTY) from None
    if len(raw) > max_bytes:
        raise _refuse(RuntimeBindingDefect.FILE_TOO_LARGE) from None
    if raw.startswith(b"\xef\xbb\xbf"):
        raise _refuse(RuntimeBindingDefect.ENCODING_INVALID) from None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _refuse(RuntimeBindingDefect.ENCODING_INVALID) from None
    try:
        return json.loads(text, object_pairs_hook=_no_duplicate_keys)
    except RuntimeBindingError:
        raise
    except Exception:
        raise _refuse(RuntimeBindingDefect.DOCUMENT_MALFORMED) from None


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise _refuse(RuntimeBindingDefect.DUPLICATE_KEY) from None
        seen[key] = value
    return seen


def load_task_runtime_binding(
    actor: ProductionActor, *, reader: ParameterReader
) -> ProductionRuntimeBinding:
    """Read and validate ``actor``'s binding parameter through an injected reader.

    The parameter name is the compiled one for this actor; nothing can redirect the
    read. The value is refused above the standard-tier ceiling **before parsing**,
    decoded under the same strict rules as the file, and parsed by the same
    function.

    Raises:
        RuntimeBindingError: ``FILE_UNREADABLE`` if the reader raises anything at
            all -- the reader's own message is never carried -- and every decoding
            and parse defect.
    """
    constants = constants_for(actor)
    try:
        raw = reader.read_parameter(constants.binding_parameter)
    except Exception:
        raise _refuse(RuntimeBindingDefect.FILE_UNREADABLE) from None
    document = decode_parameter_document(raw, max_bytes=MAX_BINDING_PARAMETER_BYTES)
    return parse_production_runtime_binding(document, actor=actor)


__all__ = [
    "BINDING_SCHEMA_VERSION",
    "ParameterReader",
    "ProductionRuntimeBinding",
    "binding_fields",
    "decode_parameter_document",
    "human_binding_path",
    "load_human_runtime_binding",
    "load_task_runtime_binding",
    "parse_production_runtime_binding",
]
