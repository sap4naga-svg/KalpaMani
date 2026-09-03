"""The private runtime binding that supplies the licensed bucket (ADR-0023).

**Why this module exists.** The ADR-0018 Run A acquisition entry point resolved the
licensed bucket from governed Terraform remote state. Terraform inherits the process
environment, so it ran under the acquisition actor's own profile -- and that actor is
deliberately write-only: ADR-0019 gives it ``s3:PutObject`` and an explicit ``Deny``
on every read action, and it holds no authority at all on the state bucket. The read
therefore could not succeed, and Run A refused at stage 6 before reaching a
credential, a provider request or a write.

**Widening the actor was the wrong repair.** Terraform state carries the whole
infrastructure inventory and can hold plaintext-sensitive values, so granting the
acquisition actor state access would have handed a compromised acquisition process
exactly the reach ADR-0019 removed. The bucket name is configuration, not a
credential -- so it arrives as configuration, out of band, and the IAM policy is
untouched.

**What arrives, and how it is trusted.** One ACL-protected private JSON file,
selected by absolute path through :data:`RUNTIME_BINDING_ENV_VAR`. There is no
default path, no directory scan, no newest-file selection and no fallback: the
variable names the exact file, or nothing is read at all. Before a byte is parsed the
file must sit beneath the current user's own private root, be a regular file reached
through no link, be owned by the current user, and carry exactly one Allow entry --
their own -- with inheritance off and no Deny entry anywhere.

**Every refusal is a closed member naming a rule.** A path, an account, a bucket, a
digest, a JSON fragment, a user name and a security identifier are each private, and
none of them has a parameter to arrive through. The caller converts the refusal into
its own allowlisted outcome; nothing lower-level reaches a transcript.

**This module writes nothing and creates nothing.** It does not scaffold a binding,
create the private root, or repair a permission -- the file is the owner's, made under
a separately authorized materialization gate and approved by a separate independent
review. A tool that helpfully wrote one is a tool that invites a placeholder to be
mistaken for a decision.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

#: The one fixed, non-secret environment-variable *name* that selects the binding.
#: The name is a public part of the contract; the value is a private path, and it is
#: never printed, logged, returned or included in a refusal.
RUNTIME_BINDING_ENV_VAR: Final = "KALPAMANI_QUALIFICATION_RUNTIME_BINDING_FILE"

#: The one schema version this loader accepts. An exact match, not a minimum: a file
#: written for a different shape is refused rather than interpreted.
RUNTIME_BINDING_SCHEMA_VERSION: Final = 1

#: The document's self-declared kind. A second, independent statement of what the
#: file is, so a differently shaped private JSON file that happened to carry the
#: right version number is still refused.
RUNTIME_BINDING_KIND: Final = "kalpamani-qualification-runtime"

#: The contract this loader implements, version included. Distinct from the schema
#: version on purpose: the schema is the shape, the contract is the meaning, and a
#: later revision may change one without the other.
RUNTIME_BINDING_CONTRACT_ID: Final = "qualification-runtime-binding/v1"

#: Largest private input this loader will read, in bytes. The document is on the
#: order of half a kilobyte; the ceiling exists so a wrong path cannot make the
#: loader read something enormous before refusing it.
MAX_RUNTIME_BINDING_BYTES: Final = 16 * 1024

#: The governed AWS partition, region and acquisition profile. Restated here and
#: compared rather than accepted from the file: a binding is a private input, and an
#: input that could select its own partition, region or profile would be a routing
#: decision taken outside the repository. A test asserts these are the same literals
#: the acquisition entry point pins, so the two spellings cannot drift.
EXPECTED_PARTITION: Final = "aws"
EXPECTED_REGION: Final = "us-east-1"
EXPECTED_ACQUISITION_PROFILE: Final = "kalpamani-qualification-acquisition"

#: The environment variable naming the current user's local application data root,
#: and the two segments beneath it that form the private boundary. The canonical
#: production location is ``%LOCALAPPDATA%\\KalpaMani\\private``. **This module never
#: enumerates that directory**: it is a containment boundary, not a search path.
PRIVATE_ROOT_ENV_VAR: Final = "LOCALAPPDATA"
PRIVATE_ROOT_SEGMENTS: Final[tuple[str, ...]] = ("KalpaMani", "private")

#: The S3 bucket-name shape this loader will admit.
#:
#: **Spelled here rather than imported**, so this module does not reach into another
#: module's private names -- and a test asserts every spelling of it is identical,
#: which is the check that would catch a drift an import would merely have hidden.
#: It exists to refuse an ARN, an ``s3://`` URI, a path or a typo before any of them
#: reaches a request, and it is deliberately not an exhaustive AWS validator.
_BUCKET_NAME: Final = re.compile(r"^[a-z0-9][a-z0-9.\-]{1,61}[a-z0-9]$")

#: A twelve-digit AWS account number, and nothing else.
_ACCOUNT_ID: Final = re.compile(r"^[0-9]{12}$")

#: A Git object name: lowercase hex, exactly forty characters.
_GIT_OBJECT: Final = re.compile(r"^[0-9a-f]{40}$")

#: A SHA-256 digest: lowercase hex, exactly sixty-four characters.
_SHA256_HEX: Final = re.compile(r"^[0-9a-f]{64}$")

#: The exact top-level field set. An allowlist: a field nobody anticipated is refused
#: rather than ignored, because an ignored field is a decision that silently did not
#: happen.
_DOCUMENT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "binding_kind",
        "contract_id",
        "aws_partition",
        "aws_region",
        "target_account_id",
        "acquisition_profile",
        "licensed_bucket_name",
        "provenance",
    }
)

#: The exact provenance field set, same rule. These are populated and independently
#: verified at the later materialization gate. They are not secrets, and they are
#: private operational metadata: they are validated for shape and never returned.
_PROVENANCE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "implementation_commit",
        "implementation_tree",
        "environment_binding_sha256",
    }
)


class RuntimeBindingDefect(StrEnum):
    """Why a private runtime binding was refused. A closed, structural vocabulary.

    **No member can carry a value**, which is the point. A filesystem error quotes a
    path, a security error quotes a user name or a security identifier, a JSON
    decoder quotes the offending line, and a field refusal would quote an account or
    a bucket. Every member names a rule instead, and the owner reads their own file
    to see which one their file broke.
    """

    ENVIRONMENT_UNSET = "ENVIRONMENT_UNSET"
    PATH_NOT_ABSOLUTE = "PATH_NOT_ABSOLUTE"
    PRIVATE_ROOT_UNRESOLVED = "PRIVATE_ROOT_UNRESOLVED"
    PATH_OUTSIDE_PRIVATE_ROOT = "PATH_OUTSIDE_PRIVATE_ROOT"
    PATH_NOT_A_REGULAR_FILE = "PATH_NOT_A_REGULAR_FILE"
    PATH_IS_A_LINK = "PATH_IS_A_LINK"
    SECURITY_UNVERIFIABLE = "SECURITY_UNVERIFIABLE"
    OWNER_NOT_CURRENT_USER = "OWNER_NOT_CURRENT_USER"
    ACL_INHERITANCE_ENABLED = "ACL_INHERITANCE_ENABLED"
    ACL_NOT_EXCLUSIVE = "ACL_NOT_EXCLUSIVE"
    ACL_DENY_PRESENT = "ACL_DENY_PRESENT"
    FILE_EMPTY = "FILE_EMPTY"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    FILE_UNREADABLE = "FILE_UNREADABLE"
    FILE_CHANGED_DURING_READ = "FILE_CHANGED_DURING_READ"
    ENCODING_INVALID = "ENCODING_INVALID"
    DOCUMENT_MALFORMED = "DOCUMENT_MALFORMED"
    DUPLICATE_KEY = "DUPLICATE_KEY"
    FIELD_UNKNOWN = "FIELD_UNKNOWN"
    FIELD_MISSING = "FIELD_MISSING"
    FIELD_MALFORMED = "FIELD_MALFORMED"
    SCHEMA_VERSION_UNKNOWN = "SCHEMA_VERSION_UNKNOWN"
    BINDING_KIND_UNKNOWN = "BINDING_KIND_UNKNOWN"
    CONTRACT_ID_UNKNOWN = "CONTRACT_ID_UNKNOWN"
    PARTITION_UNEXPECTED = "PARTITION_UNEXPECTED"
    REGION_UNEXPECTED = "REGION_UNEXPECTED"
    PROFILE_UNEXPECTED = "PROFILE_UNEXPECTED"
    ACCOUNT_MALFORMED = "ACCOUNT_MALFORMED"
    ACCOUNT_MISMATCH = "ACCOUNT_MISMATCH"
    EXPECTED_ACCOUNT_UNAVAILABLE = "EXPECTED_ACCOUNT_UNAVAILABLE"
    BUCKET_NAME_MALFORMED = "BUCKET_NAME_MALFORMED"
    PROVENANCE_MALFORMED = "PROVENANCE_MALFORMED"


class RuntimeBindingError(Exception):
    """A refusal carrying exactly one :class:`RuntimeBindingDefect` and nothing else.

    Raised ``from None`` everywhere, always. The message is the member's token, so
    both reprs, the string form and any traceback carry a rule name and never a
    value.
    """

    __slots__ = ("defect",)

    def __init__(self, defect: RuntimeBindingDefect) -> None:
        """Bind the defect. The message is the member's token, nothing more."""
        if type(defect) is not RuntimeBindingDefect:  # pragma: no cover - type guard
            raise TypeError("a defect must be an exact RuntimeBindingDefect member")
        super().__init__(defect.value)
        self.defect = defect


def _refuse(defect: RuntimeBindingDefect) -> RuntimeBindingError:
    return RuntimeBindingError(defect)


@dataclass(frozen=True, slots=True, kw_only=True)
class FileSecurity:
    """What the platform reports about one file's owner and discretionary ACL.

    A value object, so the policy above it is decided in ordinary Python and can be
    driven from a synthetic inspector in a test. **The production inspector is still
    the real one**, and a platform that cannot answer fails closed rather than
    skipping the question.

    ``current_principal``, ``owner`` and the two principal tuples are opaque platform
    identifiers -- security identifiers on Windows. They are compared and never
    rendered: :meth:`__repr__` is a summary for the same reason the inventory's is.
    """

    current_principal: str
    owner: str
    inheritance_disabled: bool
    allow_principals: tuple[str, ...]
    deny_principals: tuple[str, ...]

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing: a subclass could give the principals a ``__repr__``."""
        raise TypeError("FileSecurity may not be subclassed")

    def __repr__(self) -> str:
        """Counts and one flag. **Never a principal, and never an owner.**"""
        return (
            "FileSecurity("
            f"protected={self.inheritance_disabled}, "
            f"allow={len(self.allow_principals)}, "
            f"deny={len(self.deny_principals)})"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class QualificationRuntimeBinding:
    """The validated runtime values, and only the ones runtime needs.

    **The private account number is deliberately absent.** It is validated against
    the governed expected account and then dropped: a caller that never receives it
    cannot print it, and the identity gate one stage earlier is what proves the
    account anyway.

    ``licensed_bucket_name`` is private, so ``__repr__`` omits it -- no logging call,
    assertion failure or debugger echo can spill it.
    """

    licensed_bucket_name: str
    partition: str
    region: str
    acquisition_profile: str

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing: a subclass could give the bucket a ``__repr__``."""
        raise TypeError("QualificationRuntimeBinding may not be subclassed")

    def __repr__(self) -> str:
        """The governed public values only. **Never the bucket.**"""
        return (
            "QualificationRuntimeBinding("
            f"partition={self.partition!r}, "
            f"region={self.region!r}, "
            f"profile={self.acquisition_profile!r})"
        )


# ---------------------------------------------------------------------------
# The platform security inspector -- real, and fail-closed
# ---------------------------------------------------------------------------

#: ``SE_FILE_OBJECT``: the object type ``GetNamedSecurityInfoW`` is asked about.
_SE_FILE_OBJECT: Final = 1

#: The two pieces of the security descriptor this loader needs, and no more.
_OWNER_SECURITY_INFORMATION: Final = 0x00000001
_DACL_SECURITY_INFORMATION: Final = 0x00000004

#: ``SE_DACL_PROTECTED``: set when the DACL does **not** inherit from its parent.
_SE_DACL_PROTECTED: Final = 0x1000

#: The only two ACE types this loader will classify. Anything else -- an audit, an
#: object or a callback entry -- is unclassifiable, and an unclassifiable entry is a
#: permission nobody has evaluated.
_ACCESS_ALLOWED_ACE_TYPE: Final = 0x00
_ACCESS_DENIED_ACE_TYPE: Final = 0x01

#: ``TOKEN_QUERY``, and the ``TokenUser`` information class.
_TOKEN_QUERY: Final = 0x0008
_TOKEN_USER_CLASS: Final = 1


class _AceHeader(ctypes.Structure):
    """``ACE_HEADER``: the type, flags and size every entry begins with."""

    _fields_ = (
        ("AceType", ctypes.c_ubyte),
        ("AceFlags", ctypes.c_ubyte),
        ("AceSize", ctypes.c_ushort),
    )


class _KnownAce(ctypes.Structure):
    """``ACCESS_ALLOWED_ACE`` and ``ACCESS_DENIED_ACE`` -- identical in layout."""

    _fields_ = (
        ("Header", _AceHeader),
        ("Mask", ctypes.c_uint32),
        ("SidStart", ctypes.c_uint32),
    )


class _Acl(ctypes.Structure):
    """``ACL``: the header in front of the access-control entries."""

    _fields_ = (
        ("AclRevision", ctypes.c_ubyte),
        ("Sbz1", ctypes.c_ubyte),
        ("AclSize", ctypes.c_ushort),
        ("AceCount", ctypes.c_ushort),
        ("Sbz2", ctypes.c_ushort),
    )


class _SidAndAttributes(ctypes.Structure):
    """``SID_AND_ATTRIBUTES``, as carried by a ``TOKEN_USER``."""

    _fields_ = (("Sid", ctypes.c_void_p), ("Attributes", ctypes.c_uint32))


class _TokenUser(ctypes.Structure):
    """``TOKEN_USER``: the security identifier the process is running as."""

    _fields_ = (("User", _SidAndAttributes),)


#: Where the security identifier starts inside an allow or deny entry. Computed from
#: the structure sizes rather than written as ``8``, so it stays correct if the
#: declarations above ever change.
_ACE_SID_OFFSET: Final = ctypes.sizeof(_AceHeader) + ctypes.sizeof(ctypes.c_uint32)


def _libraries() -> tuple[Any, Any]:
    """The two system libraries, with every prototype declared before it is called.

    **Declared rather than left to ctypes' defaults**, because the defaults are what
    made the first version of this wrong: an undeclared argument is treated as a
    C ``int``, and ``GetCurrentProcess`` answers with a pseudo-handle that does not
    fit in one. A handle silently truncated to the wrong width is the class of bug
    that produces a *plausible* answer about a security boundary.
    """
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    handle = ctypes.c_void_p
    handle_out = ctypes.POINTER(ctypes.c_void_p)

    kernel32.GetCurrentProcess.argtypes = ()
    kernel32.GetCurrentProcess.restype = handle
    kernel32.CloseHandle.argtypes = (handle,)
    kernel32.CloseHandle.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = (handle,)
    kernel32.LocalFree.restype = handle

    advapi32.GetNamedSecurityInfoW.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_int,
        ctypes.c_uint32,
        handle_out,
        handle_out,
        handle_out,
        handle_out,
        handle_out,
    )
    advapi32.GetNamedSecurityInfoW.restype = ctypes.c_uint32
    advapi32.GetSecurityDescriptorControl.argtypes = (
        handle,
        ctypes.POINTER(ctypes.c_uint16),
        ctypes.POINTER(ctypes.c_uint32),
    )
    advapi32.GetSecurityDescriptorControl.restype = ctypes.c_int
    advapi32.GetAce.argtypes = (handle, ctypes.c_uint32, handle_out)
    advapi32.GetAce.restype = ctypes.c_int
    advapi32.ConvertSidToStringSidW.argtypes = (handle, ctypes.POINTER(ctypes.c_wchar_p))
    advapi32.ConvertSidToStringSidW.restype = ctypes.c_int
    advapi32.OpenProcessToken.argtypes = (handle, ctypes.c_uint32, handle_out)
    advapi32.OpenProcessToken.restype = ctypes.c_int
    advapi32.GetTokenInformation.argtypes = (
        handle,
        ctypes.c_int,
        handle,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
    )
    advapi32.GetTokenInformation.restype = ctypes.c_int
    return advapi32, kernel32


def _sid_text(advapi32: Any, kernel32: Any, sid: Any) -> str:
    """One security identifier, in its canonical string form.

    The buffer ``ConvertSidToStringSidW`` allocates is freed here, in a ``finally``,
    because this runs inside a loop over an ACL and a leak per entry is still a leak.
    """
    buffer = ctypes.c_wchar_p()
    if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(buffer)):
        raise OSError(ctypes.get_last_error(), "a security identifier is unreadable")
    try:
        text = buffer.value
        if not text:
            raise OSError(0, "a security identifier converted to nothing")
        return str(text)
    finally:
        kernel32.LocalFree(ctypes.cast(buffer, ctypes.c_void_p))


def _current_principal(advapi32: Any, kernel32: Any) -> str:
    """The security identifier this process is running as.

    Read from the process token rather than from a user *name*: a name is ambiguous
    across a rename and across two machines, and an ACL carries identifiers.
    """
    token = ctypes.c_void_p()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)
    ):
        raise OSError(ctypes.get_last_error(), "the process token could not be opened")
    try:
        size = ctypes.c_uint32(0)
        advapi32.GetTokenInformation(token, _TOKEN_USER_CLASS, None, 0, ctypes.byref(size))
        if size.value == 0:
            raise OSError(ctypes.get_last_error(), "the process token reported no size")
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(
            token,
            _TOKEN_USER_CLASS,
            ctypes.cast(buffer, ctypes.c_void_p),
            size.value,
            ctypes.byref(size),
        ):
            raise OSError(ctypes.get_last_error(), "the process token could not be read")
        user = ctypes.cast(buffer, ctypes.POINTER(_TokenUser)).contents
        return _sid_text(advapi32, kernel32, user.User.Sid)
    finally:
        kernel32.CloseHandle(token)


def _read_windows_file_security(path: Path) -> FileSecurity:
    """Owner, inheritance state and every discretionary entry, from the platform.

    Deliberately narrow: the owner and the DACL, and nothing else. The system ACL is
    not requested, because reading one needs a privilege this process should not hold
    and this loader has no question an audit entry would answer.
    """
    advapi32, kernel32 = _libraries()

    owner = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    status = advapi32.GetNamedSecurityInfoW(
        ctypes.c_wchar_p(str(path)),
        _SE_FILE_OBJECT,
        _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
        ctypes.byref(owner),
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    if status != 0:
        raise OSError(int(status), "the security descriptor could not be read")
    try:
        control = ctypes.c_uint16()
        revision = ctypes.c_uint32()
        if not advapi32.GetSecurityDescriptorControl(
            descriptor, ctypes.byref(control), ctypes.byref(revision)
        ):
            raise OSError(ctypes.get_last_error(), "the descriptor control is unreadable")
        if not dacl:
            # A NULL DACL grants everyone full control. It is not "no entries"; it is
            # the widest possible grant, and reading it as an empty allow list would
            # invert the check this loader exists to perform.
            raise OSError(0, "the object carries no discretionary access control list")

        entries = ctypes.cast(dacl, ctypes.POINTER(_Acl)).contents
        allow: list[str] = []
        deny: list[str] = []
        for index in range(entries.AceCount):
            pointer = ctypes.c_void_p()
            if not advapi32.GetAce(dacl, index, ctypes.byref(pointer)):
                raise OSError(ctypes.get_last_error(), "an access control entry is unreadable")
            ace = ctypes.cast(pointer, ctypes.POINTER(_KnownAce)).contents
            sid = ctypes.c_void_p(int(pointer.value or 0) + _ACE_SID_OFFSET)
            principal = _sid_text(advapi32, kernel32, sid)
            if ace.Header.AceType == _ACCESS_ALLOWED_ACE_TYPE:
                allow.append(principal)
            elif ace.Header.AceType == _ACCESS_DENIED_ACE_TYPE:
                deny.append(principal)
            else:
                raise OSError(0, "an access control entry is of an unclassifiable type")

        return FileSecurity(
            current_principal=_current_principal(advapi32, kernel32),
            owner=_sid_text(advapi32, kernel32, owner),
            inheritance_disabled=bool(control.value & _SE_DACL_PROTECTED),
            allow_principals=tuple(allow),
            deny_principals=tuple(deny),
        )
    finally:
        kernel32.LocalFree(descriptor)


def windows_file_security(path: Path) -> FileSecurity:
    """The production inspector. **Any failure to answer is a refusal.**

    A platform that cannot report an owner, an inheritance flag and a classifiable
    entry for every ACE has not verified the boundary, and an unverified boundary is
    not a satisfied one. There is no "checked where supported" path: the loader is
    Windows-only because the operator workstation is, and anywhere else this raises.
    """
    try:
        return _read_windows_file_security(path)
    except Exception:
        raise _refuse(RuntimeBindingDefect.SECURITY_UNVERIFIABLE) from None


# ---------------------------------------------------------------------------
# Path selection and containment
# ---------------------------------------------------------------------------


def environment_binding_path() -> str:
    """The binding path, from the one fixed environment-variable name.

    The *name* is a constant and is not a secret; the *value* is a private path, and
    it is never printed, logged, returned in a result or included in a refusal.

    Raises:
        RuntimeBindingError: ``ENVIRONMENT_UNSET`` if the variable is absent or
            blank. **There is no default path**: a loader that fell back to a
            location of its own would read a file nobody selected.
    """
    value = os.environ.get(RUNTIME_BINDING_ENV_VAR, "")
    if not value.strip():
        raise _refuse(RuntimeBindingDefect.ENVIRONMENT_UNSET) from None
    return value


def private_root() -> Path:
    """The current user's private boundary: ``%LOCALAPPDATA%\\KalpaMani\\private``.

    **A containment boundary, never a search path.** Nothing here lists it, globs it,
    creates it or picks a file out of it -- the environment variable names the exact
    file, and this only answers whether that file is inside.

    Raises:
        RuntimeBindingError: ``PRIVATE_ROOT_UNRESOLVED`` if the platform reports no
            usable local application data root.
    """
    base = os.environ.get(PRIVATE_ROOT_ENV_VAR, "")
    if not base.strip():
        raise _refuse(RuntimeBindingDefect.PRIVATE_ROOT_UNRESOLVED) from None
    root = Path(base)
    if not root.is_absolute():
        raise _refuse(RuntimeBindingDefect.PRIVATE_ROOT_UNRESOLVED) from None
    return root.joinpath(*PRIVATE_ROOT_SEGMENTS)


def _normalised(path: Path) -> Path:
    """``path`` with ``.`` and ``..`` removed **lexically**, following no link.

    Lexical on purpose. ``Path.resolve`` would follow a junction and hand back the
    target's canonical location, so a link inside the private root pointing anywhere
    at all would canonicalise to something this loader then measured against the
    wrong boundary.
    """
    return Path(os.path.normpath(str(path)))


def _is_link(path: Path) -> bool:
    """Whether ``path`` is a symlink, a junction, or any other reparse point."""
    try:
        entry = path.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(entry.st_mode):
        return True
    attributes = int(getattr(entry, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return bool(attributes & reparse)


def _within(candidate: Path, root: Path) -> bool:
    """Whether ``candidate`` is at or beneath ``root``, compared case-insensitively.

    ``normcase`` rather than a raw comparison: Windows paths are case-insensitive, so
    a boundary a differently cased spelling could step outside of would not be a
    boundary at all.
    """
    normalised = Path(os.path.normcase(str(candidate)))
    boundary = Path(os.path.normcase(str(root)))
    return normalised == boundary or boundary in normalised.parents


def _safe_private_path(raw: str, root: Path) -> Path:
    """One validated private path, or a refusal naming only the rule it broke.

    Three questions, in the order that makes each answer meaningful:

    1. Is the *given* string an absolute path strictly inside the boundary, once
       ``.`` and ``..`` are removed lexically? A ``..`` that walks out is refused
       here, and so is the boundary directory itself.
    2. Is every component from the boundary down to the file free of links? A
       junction anywhere in the chain would make the containment above cosmetic.
    3. Is it a regular file? A directory, a device and a pipe are each a thing this
       loader must not read.
    """
    if type(raw) is not str or not raw.strip():
        raise _refuse(RuntimeBindingDefect.ENVIRONMENT_UNSET) from None
    candidate = Path(raw.strip())
    if not candidate.is_absolute():
        raise _refuse(RuntimeBindingDefect.PATH_NOT_ABSOLUTE) from None

    normalised = _normalised(candidate)
    boundary = _normalised(root)
    if normalised == boundary or not _within(normalised, boundary):
        raise _refuse(RuntimeBindingDefect.PATH_OUTSIDE_PRIVATE_ROOT) from None

    chain = [normalised]
    for parent in normalised.parents:
        if not _within(parent, boundary):
            break
        chain.append(parent)
    for element in chain:
        if _is_link(element):
            raise _refuse(RuntimeBindingDefect.PATH_IS_A_LINK) from None

    try:
        entry = normalised.lstat()
    except OSError:
        raise _refuse(RuntimeBindingDefect.PATH_NOT_A_REGULAR_FILE) from None
    if not stat.S_ISREG(entry.st_mode):
        raise _refuse(RuntimeBindingDefect.PATH_NOT_A_REGULAR_FILE) from None
    return normalised


def _identity(path: Path) -> tuple[int, int, int, int]:
    """The stable file identity used to prove one file was read throughout."""
    try:
        entry = path.lstat()
    except OSError:
        raise _refuse(RuntimeBindingDefect.FILE_UNREADABLE) from None
    return (entry.st_dev, entry.st_ino, entry.st_size, entry.st_mtime_ns)


def _require_exclusive_security(security: object) -> None:
    """The whole ACL policy, decided in ordinary Python over one value object.

    Ordered so the first failure is the most informative: an owner who is not the
    current user says the file belongs to somebody else, which is a different problem
    from a file of theirs that too many principals can reach.
    """
    if type(security) is not FileSecurity:
        raise _refuse(RuntimeBindingDefect.SECURITY_UNVERIFIABLE) from None
    if not security.current_principal or not security.owner:
        raise _refuse(RuntimeBindingDefect.SECURITY_UNVERIFIABLE) from None
    if security.owner != security.current_principal:
        raise _refuse(RuntimeBindingDefect.OWNER_NOT_CURRENT_USER) from None
    if not security.inheritance_disabled:
        raise _refuse(RuntimeBindingDefect.ACL_INHERITANCE_ENABLED) from None
    if security.deny_principals:
        # A Deny entry is refused even when it names somebody else: this loader
        # admits exactly one reachable shape, and reasoning about a partial denial is
        # reasoning nobody should have to do about a private file.
        raise _refuse(RuntimeBindingDefect.ACL_DENY_PRESENT) from None
    if security.allow_principals != (security.current_principal,):
        raise _refuse(RuntimeBindingDefect.ACL_NOT_EXCLUSIVE) from None


# ---------------------------------------------------------------------------
# Document parsing
# ---------------------------------------------------------------------------


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """``json`` object hook that refuses a repeated key instead of keeping the last.

    The default behaviour silently keeps the last occurrence, so a document carrying
    two ``licensed_bucket_name`` entries would validate one value and use the other.
    """
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise _refuse(RuntimeBindingDefect.DUPLICATE_KEY) from None
        seen[key] = value
    return seen


def _exact_string(container: dict[str, Any], field: str) -> str:
    """One field that must be an exact ``str``. A ``bool`` is not a string."""
    value = container[field]
    if type(value) is not str:
        raise _refuse(RuntimeBindingDefect.FIELD_MALFORMED) from None
    return value


def _validate_provenance(raw: object) -> None:
    """Shape-check the provenance block. **Nothing here is returned.**

    Populated and independently verified at the later materialization gate, so the
    grammar is enforced now and the values are never carried into runtime: a digest
    the acquisition path does not need is a digest the acquisition path cannot print.
    """
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


def parse_runtime_binding(
    document: object, *, expected_account: str | None
) -> QualificationRuntimeBinding:
    """Validate an already-decoded binding document. **Reads no file.**

    Separated from :func:`load_runtime_binding` so every rule below is testable with
    synthetic structures and no filesystem at all -- which is the only way this can be
    tested, since the real binding must never exist in a test.

    Args:
        document: the decoded JSON value. Anything but an object is refused.
        expected_account: the governed account this deployment is bound to,
            supplied by the caller from the same governed source the identity gate
            reads. **No AWS call is made here**, and none is needed: the comparison is
            between two values the caller already holds.

    Raises:
        RuntimeBindingError: one closed :class:`RuntimeBindingDefect`. The refusal
            names the rule and never the value.
    """
    if expected_account is None or not _ACCOUNT_ID.match(str(expected_account)):
        raise _refuse(RuntimeBindingDefect.EXPECTED_ACCOUNT_UNAVAILABLE) from None

    if type(document) is not dict:
        raise _refuse(RuntimeBindingDefect.DOCUMENT_MALFORMED) from None
    names = set(document)
    if names - _DOCUMENT_FIELDS:
        raise _refuse(RuntimeBindingDefect.FIELD_UNKNOWN) from None
    if _DOCUMENT_FIELDS - names:
        raise _refuse(RuntimeBindingDefect.FIELD_MISSING) from None

    version = document["schema_version"]
    if type(version) is not int:
        raise _refuse(RuntimeBindingDefect.FIELD_MALFORMED) from None
    if version != RUNTIME_BINDING_SCHEMA_VERSION:
        raise _refuse(RuntimeBindingDefect.SCHEMA_VERSION_UNKNOWN) from None
    if _exact_string(document, "binding_kind") != RUNTIME_BINDING_KIND:
        raise _refuse(RuntimeBindingDefect.BINDING_KIND_UNKNOWN) from None
    if _exact_string(document, "contract_id") != RUNTIME_BINDING_CONTRACT_ID:
        raise _refuse(RuntimeBindingDefect.CONTRACT_ID_UNKNOWN) from None
    if _exact_string(document, "aws_partition") != EXPECTED_PARTITION:
        raise _refuse(RuntimeBindingDefect.PARTITION_UNEXPECTED) from None
    if _exact_string(document, "aws_region") != EXPECTED_REGION:
        raise _refuse(RuntimeBindingDefect.REGION_UNEXPECTED) from None
    if _exact_string(document, "acquisition_profile") != EXPECTED_ACQUISITION_PROFILE:
        raise _refuse(RuntimeBindingDefect.PROFILE_UNEXPECTED) from None

    account = _exact_string(document, "target_account_id")
    if not _ACCOUNT_ID.match(account):
        raise _refuse(RuntimeBindingDefect.ACCOUNT_MALFORMED) from None
    if account != expected_account:
        raise _refuse(RuntimeBindingDefect.ACCOUNT_MISMATCH) from None

    bucket = _exact_string(document, "licensed_bucket_name")
    if not _BUCKET_NAME.match(bucket):
        raise _refuse(RuntimeBindingDefect.BUCKET_NAME_MALFORMED) from None

    _validate_provenance(document["provenance"])

    return QualificationRuntimeBinding(
        licensed_bucket_name=bucket,
        partition=EXPECTED_PARTITION,
        region=EXPECTED_REGION,
        acquisition_profile=EXPECTED_ACQUISITION_PROFILE,
    )


def load_runtime_binding(
    *,
    expected_account: str | None,
    path_source: Callable[[], str] | None = None,
    root_source: Callable[[], Path] | None = None,
    security_of: Callable[[Path], FileSecurity] | None = None,
) -> QualificationRuntimeBinding:
    """Read and validate the private runtime binding the environment selects.

    The order is the security property. Containment and ownership are settled before
    a byte is read, so a file somewhere else, a file reached through a junction and a
    file other principals can write are each refused **without being opened**. The
    identity and the security state are then re-read afterwards, so a file swapped
    between the check and the read is refused rather than trusted.

    ``path_source``, ``root_source`` and ``security_of`` are injection seams **for
    tests only**, and each defaults to ``None`` rather than to the function itself so
    the production default is looked up when the call happens. The production
    defaults are the fixed environment variable, the current user's private root and
    the real platform inspector; no entry point exposes an option that could supply a
    different one, and the inspector cannot be silently skipped -- a platform that
    cannot answer raises ``SECURITY_UNVERIFIABLE``.

    Raises:
        RuntimeBindingError: one closed :class:`RuntimeBindingDefect`. **No refusal
            names the path, the account, the bucket, a digest, a principal or any
            fragment of the document.**
    """
    read_path = environment_binding_path if path_source is None else path_source
    read_root = private_root if root_source is None else root_source
    inspect = windows_file_security if security_of is None else security_of

    root = read_root()
    # ``isinstance`` rather than an exact type check, unlike the ``str`` guards below:
    # ``Path`` is a factory that answers with ``WindowsPath`` or ``PosixPath``, so an
    # exact check here would refuse every genuine path this ever receives.
    if not isinstance(root, Path) or not root.is_absolute():
        raise _refuse(RuntimeBindingDefect.PRIVATE_ROOT_UNRESOLVED) from None

    path = _safe_private_path(read_path(), root)

    before_security = inspect(path)
    _require_exclusive_security(before_security)
    before = _identity(path)
    if before[2] == 0:
        raise _refuse(RuntimeBindingDefect.FILE_EMPTY) from None
    if before[2] > MAX_RUNTIME_BINDING_BYTES:
        raise _refuse(RuntimeBindingDefect.FILE_TOO_LARGE) from None

    try:
        raw = path.read_bytes()
    except OSError:
        raise _refuse(RuntimeBindingDefect.FILE_UNREADABLE) from None

    if _identity(path) != before or inspect(path) != before_security:
        raise _refuse(RuntimeBindingDefect.FILE_CHANGED_DURING_READ) from None

    if not raw:
        raise _refuse(RuntimeBindingDefect.FILE_EMPTY) from None
    if len(raw) > MAX_RUNTIME_BINDING_BYTES:
        raise _refuse(RuntimeBindingDefect.FILE_TOO_LARGE) from None
    if raw.startswith(b"\xef\xbb\xbf"):
        # A byte-order mark is legal UTF-8 and is refused anyway: this contract is a
        # bare UTF-8 JSON object, and admitting an optional prefix would mean two
        # byte sequences for one document.
        raise _refuse(RuntimeBindingDefect.ENCODING_INVALID) from None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _refuse(RuntimeBindingDefect.ENCODING_INVALID) from None

    try:
        document = json.loads(text, object_pairs_hook=_no_duplicate_keys)
    except RuntimeBindingError:
        raise
    except Exception:
        raise _refuse(RuntimeBindingDefect.DOCUMENT_MALFORMED) from None

    return parse_runtime_binding(document, expected_account=expected_account)


__all__ = [
    "EXPECTED_ACQUISITION_PROFILE",
    "EXPECTED_PARTITION",
    "EXPECTED_REGION",
    "MAX_RUNTIME_BINDING_BYTES",
    "PRIVATE_ROOT_ENV_VAR",
    "PRIVATE_ROOT_SEGMENTS",
    "RUNTIME_BINDING_CONTRACT_ID",
    "RUNTIME_BINDING_ENV_VAR",
    "RUNTIME_BINDING_KIND",
    "RUNTIME_BINDING_SCHEMA_VERSION",
    "FileSecurity",
    "QualificationRuntimeBinding",
    "RuntimeBindingDefect",
    "RuntimeBindingError",
    "environment_binding_path",
    "load_runtime_binding",
    "parse_runtime_binding",
    "private_root",
    "windows_file_security",
]
