"""One rule for turning an identifier into a path component.

Every value that reaches the filesystem -- a provider name, a dataset name, an
entity, an ingestion-run id, a dataset version -- passes through here first.

**External identifiers are never unchecked path components.** A provider name is
data supplied from outside the system; treating it as a directory name means the
vendor chooses where we write. ``..`` escapes the store, an absolute path ignores
it entirely, and a name colliding with the staging prefix could make an
uncommitted build look published. None of those needs to be reachable for the
store to work, so none of them is.

The rule is deliberately narrow rather than clever: a component is a non-empty
string of letters, digits, and the four separators the layout actually uses. A
sanitiser that *rewrites* a bad name would map two different identifiers onto one
path, which is worse than refusing -- two datasets sharing a directory is a
corruption that verifies.

``dataset_version`` is the one identifier that is legitimately path-*like*
(``gold/2026.08.26.1``), so it is validated segment by segment.
"""

from __future__ import annotations

import re
from typing import Final

from kalpamani.data.contracts.errors import UnsafePathComponentError

#: Letters, digits, dot, dash, underscore. Nothing that navigates.
_SAFE_COMPONENT: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

#: Names the publication layout reserves for itself.
RESERVED_PREFIXES: Final = ("_staging-", ".tmp-")
RESERVED_NAMES: Final = ("_dataset_manifest.json", ".", "..")

#: Maximum length of one component. Not a security boundary -- a legibility one,
#: and a guard against a name that would break a filesystem somewhere.
MAX_COMPONENT_LENGTH: Final = 128


def safe_component(value: str, *, kind: str) -> str:
    """Return ``value`` unchanged, or refuse it.

    Raises:
        UnsafePathComponentError: if ``value`` is empty, over-long, navigates,
            contains a separator, or collides with a reserved name. Refusal
            rather than sanitisation: rewriting would map two identifiers onto
            one path, and two datasets sharing a directory is a corruption that
            verifies.
    """
    if not value:
        raise UnsafePathComponentError(f"{kind} is empty; an empty path component names nothing.")
    if len(value) > MAX_COMPONENT_LENGTH:
        raise UnsafePathComponentError(
            f"{kind}={value[:40]!r}... is {len(value)} characters, over the "
            f"{MAX_COMPONENT_LENGTH} limit."
        )
    if value in RESERVED_NAMES or any(value.startswith(p) for p in RESERVED_PREFIXES):
        raise UnsafePathComponentError(
            f"{kind}={value!r} collides with a name the publication layout reserves. A build "
            "that could be mistaken for staging, or for a manifest, is not publishable."
        )
    if not _SAFE_COMPONENT.match(value):
        raise UnsafePathComponentError(
            f"{kind}={value!r} is not a safe path component. Letters, digits, dot, dash and "
            "underscore only: an identifier that arrives from outside the system does not get "
            "to choose where we write."
        )
    return value


def safe_relative_path(value: str, *, kind: str) -> str:
    """Validate a path-like identifier segment by segment.

    ``dataset_version`` is conventionally ``gold/2026.08.26.1``, so it becomes
    nested directories. Every segment is held to :func:`safe_component`, and the
    whole must stay relative.
    """
    if value.startswith(("/", "\\")) or (len(value) > 1 and value[1] == ":"):
        raise UnsafePathComponentError(
            f"{kind}={value!r} is absolute. A store root that a value can escape is not a root."
        )
    segments = [segment for segment in re.split(r"[/\\]", value)]
    if not segments or any(segment == "" for segment in segments):
        raise UnsafePathComponentError(
            f"{kind}={value!r} has an empty segment; the path it names is ambiguous."
        )
    for segment in segments:
        safe_component(segment, kind=f"{kind} segment")
    return value


__all__ = [
    "MAX_COMPONENT_LENGTH",
    "RESERVED_NAMES",
    "RESERVED_PREFIXES",
    "safe_component",
    "safe_relative_path",
]
