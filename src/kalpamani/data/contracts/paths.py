"""One rule for turning an identifier into a path component.

Every value that reaches the filesystem -- a provider name, a dataset name, an
entity, an ingestion-run id, a dataset version, an internal filename -- passes
through here first.

**External identifiers are never unchecked path components.** A provider name is
data supplied from outside the system; treating it as a directory name means the
vendor chooses where we write. ``..`` escapes the store, an absolute path ignores
it entirely, and a name colliding with the staging prefix could make an
uncommitted build look published. None of that needs to be reachable for the
store to work, so none of it is.

The rule is deliberately narrow rather than clever: a component is a non-empty
string of letters, digits, and the three separators the layout actually uses. A
sanitiser that *rewrites* a bad name would map two different identifiers onto one
path, which is worse than refusing -- two datasets sharing a directory is a
corruption that verifies.

**Platform hazards are refused everywhere, not on the platform that has them.**
``CON``, ``NUL``, ``COM1`` and their relatives are device names on Windows at any
extension; a trailing dot or space is silently stripped there. A store written on
one platform is read on another, so a name that is unsafe anywhere is refused
everywhere -- otherwise the same identifier would name two different files
depending on where the code ran.

**Internal filenames are allowlisted, not pattern-matched.** Publication's own
files are named by this package, so they are compared against an exact set rather
than waved through for beginning with an underscore. A prefix rule would let
``_dataset_manifest.json/../../escape`` past.
"""

from __future__ import annotations

import re
from typing import Final

from kalpamani.data.contracts.errors import UnsafePathComponentError

#: Letters, digits, dot, dash, underscore. Nothing that navigates.
_SAFE_COMPONENT: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

#: Names the publication layout reserves for itself.
RESERVED_PREFIXES: Final = ("_staging-", ".tmp-")
RESERVED_NAMES: Final = (".", "..")

#: Reserved device names on Windows, at any extension. Refused on every platform,
#: because a store written on one is read on another.
WINDOWS_DEVICE_NAMES: Final[frozenset[str]] = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)

#: Internal filenames this package writes. An exact allowlist, not a prefix rule.
INTERNAL_FILENAMES: Final[frozenset[str]] = frozenset(
    {"_dataset_manifest.json", "_quality_report.json"}
)

#: Path *segments* this package reserves for itself inside a store layout. An exact
#: allowlist, on the same reasoning as :data:`INTERNAL_FILENAMES`.
#:
#: **Every one begins with an underscore, and that is the whole guarantee.**
#: :func:`safe_component` requires an external identifier to start with a letter or
#: a digit, so a provider, dataset or run id arriving from outside the system can
#: never spell one of these -- the collision is refused by grammar rather than by a
#: check somebody has to remember to write. A reserved segment is therefore a name
#: only this package can occupy.
RESERVED_SEGMENTS: Final[frozenset[str]] = frozenset({"_acquisition_claims"})

#: Maximum length of one component. Not a security boundary -- a legibility one,
#: and a guard against a name that would break a filesystem somewhere.
MAX_COMPONENT_LENGTH: Final = 128


def safe_component(value: str, *, kind: str) -> str:
    """Return ``value`` unchanged, or refuse it.

    Raises:
        UnsafePathComponentError: if ``value`` is empty, over-long, navigates,
            contains a separator, ends in a dot or space, collides with a
            reserved name, or matches a Windows device name. Refusal rather than
            sanitisation: rewriting would map two identifiers onto one path, and
            two datasets sharing a directory is a corruption that verifies.
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
            "that could be mistaken for staging is not publishable."
        )
    if value != value.rstrip(". "):
        raise UnsafePathComponentError(
            f"{kind}={value!r} ends in a dot or space. Windows strips those silently, so the "
            "same identifier would name two different files depending on where the code ran."
        )
    if value.split(".", 1)[0].lower() in WINDOWS_DEVICE_NAMES:
        raise UnsafePathComponentError(
            f"{kind}={value!r} is a reserved device name on Windows at any extension. It is "
            "refused on every platform, because a store written on one is read on another."
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
    segments = re.split(r"[/\\]", value)
    if not segments or any(segment == "" for segment in segments):
        raise UnsafePathComponentError(
            f"{kind}={value!r} has an empty segment; the path it names is ambiguous."
        )
    for segment in segments:
        safe_component(segment, kind=f"{kind} segment")
    return value


def path_segment(value: str, *, kind: str) -> str:
    """A safe external component, or one of this package's reserved segments.

    The single entry point for validating a segment of a store layout, so a caller
    does not have to decide which rule applies. A reserved segment is compared
    against :data:`RESERVED_SEGMENTS` exactly; everything else goes to
    :func:`safe_component` unchanged.

    Raises:
        UnsafePathComponentError: for anything that is neither.
    """
    if value in RESERVED_SEGMENTS:
        return value
    return safe_component(value, kind=kind)


def internal_filename(value: str, *, kind: str = "internal file") -> str:
    """Allow only a filename this package itself writes.

    An exact allowlist rather than a prefix rule: ``_dataset_manifest.json/../..``
    also begins with an underscore, and a rule that waved it through would be no
    rule at all.
    """
    if value not in INTERNAL_FILENAMES:
        raise UnsafePathComponentError(
            f"{kind}={value!r} is not one of this package's internal files "
            f"({sorted(INTERNAL_FILENAMES)}). Internal names are allowlisted, not matched by "
            "prefix."
        )
    return value


__all__ = [
    "INTERNAL_FILENAMES",
    "MAX_COMPONENT_LENGTH",
    "RESERVED_NAMES",
    "RESERVED_PREFIXES",
    "RESERVED_SEGMENTS",
    "WINDOWS_DEVICE_NAMES",
    "internal_filename",
    "path_segment",
    "safe_component",
    "safe_relative_path",
]
