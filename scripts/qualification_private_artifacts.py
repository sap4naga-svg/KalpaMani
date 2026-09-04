"""The one writer for owner-only qualification private artifacts (ADR-0024).

**Why one writer.** Two private artifacts now exist beneath the operator's private
root -- the environment binding a capture produces, and the runtime binding the
acquisition path reads -- and each has to be created with the same protection the
loader demands before it will read one. A second tool that decided for itself what
"owner-only" meant would be a second security model, and two security models are one
more than anybody reviews.

So the *policy* lives where it already lived: this module applies a descriptor and
then asks :func:`kalpamani.data.qualify.sharadar.runtime_binding
.require_exclusive_security` whether the result is admissible -- the same question,
answered by the same code, that the loader asks before it reads. Containment is
:func:`~kalpamani.data.qualify.sharadar.runtime_binding.contained_private_path`, for
the same reason.

**Creation is one atomic syscall.** ``O_CREAT | O_EXCL`` either creates the file or
fails; nothing here checks for existence and then writes, because a check followed by
a write is a race, and losing that race would overwrite a private artifact somebody
else's run is bound to. **A collision is a refusal**, never a replacement.

**Nothing partial survives a failure.** If the payload cannot be written, the
descriptor cannot be applied, or the result does not satisfy the loader's own policy,
the file is removed before the refusal is raised. A half-written private artifact that
stayed on disk would be read by the next run as though somebody meant it.

**This module makes no AWS call, starts no process and reads no configuration.** It
takes an absolute destination and a byte payload, both from its caller.
"""

from __future__ import annotations

import ctypes
import os
import stat
import sys
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

REPO_ROOT: Final = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(REPO_ROOT / "src"))

from kalpamani.data.qualify.sharadar.runtime_binding import (  # noqa: E402
    FileSecurity,
    RuntimeBindingError,
    contained_private_path,
    private_root,
    require_exclusive_security,
    windows_file_security,
)

#: ``SE_FILE_OBJECT``: the object type ``SetNamedSecurityInfoW`` is told about.
_SE_FILE_OBJECT: Final = 1

#: The security information this writer sets. ``PROTECTED`` is the half that turns
#: inheritance off -- without it the parent directory's entries would flow in, and the
#: loader would refuse the result with ``ACL_INHERITANCE_ENABLED``.
_OWNER_SECURITY_INFORMATION: Final = 0x00000001
_DACL_SECURITY_INFORMATION: Final = 0x00000004
_PROTECTED_DACL_SECURITY_INFORMATION: Final = 0x80000000

#: ``ACL_REVISION``, and the access the single Allow entry grants its owner.
_ACL_REVISION: Final = 2
_FILE_ALL_ACCESS: Final = 0x001F01FF

#: The discretionary ACL buffer. Larger than one entry needs, which is allowed: an
#: ACL may carry unused space, and a computed-to-the-byte buffer is a place for an
#: arithmetic mistake to become a memory error.
_ACL_BUFFER_BYTES: Final = 1024

#: ``ERROR_SUCCESS`` -- the only return value from ``SetNamedSecurityInfoW`` that
#: means the descriptor was applied.
_ERROR_SUCCESS: Final = 0

#: Largest private artifact this writer will create. The same ceiling the loaders
#: read under, so a payload this accepts cannot be one they would refuse for size.
MAX_PRIVATE_ARTIFACT_BYTES: Final = 16 * 1024


class PrivateArtifactDefect(StrEnum):
    """Why a private artifact was not created. A closed, structural vocabulary.

    **No member carries a value.** A filesystem error quotes a path, a security error
    quotes a user name or a security identifier, and either would put a private
    location or a principal into a transcript. Every member names a rule instead, and
    the owner inspects their own directory to see which one applies.
    """

    PAYLOAD_MALFORMED = "PAYLOAD_MALFORMED"
    PAYLOAD_EMPTY = "PAYLOAD_EMPTY"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    PATH_REFUSED = "PATH_REFUSED"
    DIRECTORY_MISSING = "DIRECTORY_MISSING"
    DESTINATION_OCCUPIED = "DESTINATION_OCCUPIED"
    WRITE_FAILED = "WRITE_FAILED"
    SECURITY_APPLY_FAILED = "SECURITY_APPLY_FAILED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"


class PrivateArtifactError(Exception):
    """A refusal carrying exactly one :class:`PrivateArtifactDefect` and nothing else.

    Raised ``from None`` everywhere, always. The message is the member's token, so
    both reprs, the string form and any traceback carry a rule name and never a
    value.
    """

    __slots__ = ("defect",)

    def __init__(self, defect: PrivateArtifactDefect) -> None:
        """Bind the defect. The message is the member's token, nothing more."""
        if type(defect) is not PrivateArtifactDefect:  # pragma: no cover - type guard
            raise TypeError("a defect must be an exact PrivateArtifactDefect member")
        super().__init__(defect.value)
        self.defect = defect


def _refuse(defect: PrivateArtifactDefect) -> PrivateArtifactError:
    return PrivateArtifactError(defect)


# ---------------------------------------------------------------------------
# The platform descriptor -- real, and fail-closed
# ---------------------------------------------------------------------------


def _libraries() -> tuple[Any, Any]:
    """The two Windows libraries this writer calls, with argument types declared."""
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    advapi32.ConvertStringSidToSidW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.ConvertStringSidToSidW.restype = ctypes.c_int
    advapi32.GetLengthSid.argtypes = [ctypes.c_void_p]
    advapi32.GetLengthSid.restype = ctypes.c_uint32
    advapi32.InitializeAcl.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
    advapi32.InitializeAcl.restype = ctypes.c_int
    advapi32.AddAccessAllowedAce.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    advapi32.AddAccessAllowedAce.restype = ctypes.c_int
    advapi32.SetNamedSecurityInfoW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_int,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    advapi32.SetNamedSecurityInfoW.restype = ctypes.c_uint32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return advapi32, kernel32


def apply_exclusive_security(path: Path, principal: str) -> None:
    """Give ``path`` one Allow entry for ``principal``, own it, and stop inheritance.

    ``principal`` is a security-identifier string the caller obtained by asking the
    production inspector about this very file, so no separate identity lookup exists
    here to disagree with the one the loader performs.

    Raises:
        PrivateArtifactError: ``SECURITY_APPLY_FAILED`` if any platform call refuses.
            **The platform's own error text is not carried**: it names the path.
    """
    advapi32, kernel32 = _libraries()
    sid = ctypes.c_void_p()
    if not advapi32.ConvertStringSidToSidW(principal, ctypes.byref(sid)):
        raise _refuse(PrivateArtifactDefect.SECURITY_APPLY_FAILED) from None
    try:
        acl = ctypes.create_string_buffer(_ACL_BUFFER_BYTES)
        if not advapi32.InitializeAcl(acl, _ACL_BUFFER_BYTES, _ACL_REVISION):
            raise _refuse(PrivateArtifactDefect.SECURITY_APPLY_FAILED) from None
        if not advapi32.AddAccessAllowedAce(acl, _ACL_REVISION, _FILE_ALL_ACCESS, sid):
            raise _refuse(PrivateArtifactDefect.SECURITY_APPLY_FAILED) from None
        status = advapi32.SetNamedSecurityInfoW(
            str(path),
            _SE_FILE_OBJECT,
            _OWNER_SECURITY_INFORMATION
            | _DACL_SECURITY_INFORMATION
            | _PROTECTED_DACL_SECURITY_INFORMATION,
            sid,
            None,
            acl,
            None,
        )
        if status != _ERROR_SUCCESS:
            raise _refuse(PrivateArtifactDefect.SECURITY_APPLY_FAILED) from None
    finally:
        kernel32.LocalFree(sid)


# ---------------------------------------------------------------------------
# The writer
# ---------------------------------------------------------------------------


def _discard(path: Path) -> None:
    """Remove a partial artifact. A failure to remove it must not mask the refusal."""
    try:
        os.unlink(path)
    except OSError:
        pass


def _resolved_root(root_source: Callable[[], Path] | None) -> Path:
    root = (private_root if root_source is None else root_source)()
    if not isinstance(root, Path) or not root.is_absolute():
        raise _refuse(PrivateArtifactDefect.PATH_REFUSED) from None
    return root


def write_private_artifact(
    *,
    destination: str,
    payload: bytes,
    root_source: Callable[[], Path] | None = None,
    security_of: Callable[[Path], FileSecurity] | None = None,
    apply_security: Callable[[Path, str], None] | None = None,
) -> Path:
    """Create one owner-only private artifact, or refuse without leaving a file.

    The order is the property, and every step of it can only narrow what the next one
    sees:

    1. the payload is exact ``bytes``, non-empty, and within the ceiling the loaders
       read under;
    2. the destination is absolute, strictly inside the private boundary, and reached
       through no link at any depth;
    3. its parent directory already exists -- **this creates no directory**, because a
       directory this made would carry whatever descriptor it inherited, and the
       private root is the owner's to establish;
    4. the file is created by one atomic exclusive create, so an occupied name is a
       refusal rather than an overwrite;
    5. the bytes are written and flushed to the device;
    6. the owner, the single Allow entry and the inheritance flag are applied;
    7. the result is read back and re-verified -- the security through the loader's
       own policy, and the content byte for byte.

    ``root_source``, ``security_of`` and ``apply_security`` are injection seams **for
    tests only**, each defaulting to ``None`` rather than to the function itself, so
    the production default is looked up when the call happens.

    Returns:
        The normalised path that was created.

    Raises:
        PrivateArtifactError: one closed :class:`PrivateArtifactDefect`. **No refusal
            names the path, the payload, a principal or a platform message.**
    """
    if type(payload) is not bytes:
        raise _refuse(PrivateArtifactDefect.PAYLOAD_MALFORMED) from None
    if not payload:
        raise _refuse(PrivateArtifactDefect.PAYLOAD_EMPTY) from None
    if len(payload) > MAX_PRIVATE_ARTIFACT_BYTES:
        raise _refuse(PrivateArtifactDefect.PAYLOAD_TOO_LARGE) from None

    inspect = windows_file_security if security_of is None else security_of
    apply_descriptor = apply_exclusive_security if apply_security is None else apply_security

    root = _resolved_root(root_source)
    try:
        path = contained_private_path(destination, root)
    except RuntimeBindingError:
        # The containment vocabulary is the loader's and names a private location's
        # rule; this surface reports only that the path was refused.
        raise _refuse(PrivateArtifactDefect.PATH_REFUSED) from None

    parent = path.parent
    try:
        entry = parent.lstat()
    except OSError:
        raise _refuse(PrivateArtifactDefect.DIRECTORY_MISSING) from None
    if not stat.S_ISDIR(entry.st_mode):
        raise _refuse(PrivateArtifactDefect.DIRECTORY_MISSING) from None

    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    try:
        handle = os.open(path, flags, 0o600)
    except FileExistsError:
        raise _refuse(PrivateArtifactDefect.DESTINATION_OCCUPIED) from None
    except OSError:
        raise _refuse(PrivateArtifactDefect.WRITE_FAILED) from None

    try:
        with os.fdopen(handle, "wb") as sink:
            sink.write(payload)
            sink.flush()
            os.fsync(sink.fileno())
    except OSError:
        _discard(path)
        raise _refuse(PrivateArtifactDefect.WRITE_FAILED) from None

    try:
        before = inspect(path)
    except Exception:
        _discard(path)
        raise _refuse(PrivateArtifactDefect.VERIFICATION_FAILED) from None
    if type(before) is not FileSecurity or not before.current_principal:
        _discard(path)
        raise _refuse(PrivateArtifactDefect.VERIFICATION_FAILED) from None

    try:
        apply_descriptor(path, before.current_principal)
    except PrivateArtifactError:
        _discard(path)
        raise
    except Exception:
        _discard(path)
        raise _refuse(PrivateArtifactDefect.SECURITY_APPLY_FAILED) from None

    try:
        after = inspect(path)
        require_exclusive_security(after)
        written = path.read_bytes()
    except Exception:
        _discard(path)
        raise _refuse(PrivateArtifactDefect.VERIFICATION_FAILED) from None
    if written != payload:
        _discard(path)
        raise _refuse(PrivateArtifactDefect.VERIFICATION_FAILED) from None

    return path


__all__ = [
    "MAX_PRIVATE_ARTIFACT_BYTES",
    "PrivateArtifactDefect",
    "PrivateArtifactError",
    "apply_exclusive_security",
    "write_private_artifact",
]
