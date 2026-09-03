"""The ADR-0023 private runtime binding: containment, ownership, and the contract.

**Every value here is invented.** No real account, bucket, path, principal, commit or
digest appears, and the real binding must never exist while this suite runs -- which
is exactly why the loader takes three injection seams and why the private root is a
temporary directory in every test below.

The suite is arranged the way the loader is ordered, because the order *is* the
security property: the path is settled before the file is opened, ownership before a
byte is read, and the document only afterwards. A test that reached the JSON rules
without passing the ones above it would be testing a loader nobody wrote.
"""

from __future__ import annotations

import json
import os
import socket
import stat
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import pytest

from kalpamani.data.qualify.sharadar import runtime_binding as rb

# -- synthetic values ---------------------------------------------------------
#
# Security identifiers are the documented well-known constants plus two invented
# per-machine ones; the account, bucket, commit, tree and digest are invented and
# match no deployment. They double as leak canaries further down.

CURRENT: Final = "S-1-5-21-0-0-0-1001"
OTHER_USER: Final = "S-1-5-21-0-0-0-1002"
SYSTEM: Final = "S-1-5-18"
ADMINISTRATORS: Final = "S-1-5-32-544"
LOCAL_USERS: Final = "S-1-5-32-545"
AUTHENTICATED_USERS: Final = "S-1-5-11"
EVERYONE: Final = "S-1-1-0"

ACCOUNT: Final = "000000000000"
OTHER_ACCOUNT: Final = "999999999999"
BUCKET: Final = "synthetic-licensed-bucket-zz"
COMMIT: Final = "0123456789abcdef0123456789abcdef01234567"
TREE: Final = "89abcdef0123456789abcdef0123456789abcdef"
ENVELOPE: Final = "0123456789abcdef" * 4

#: Every synthetic private value, in one place, so the leak scan below cannot drift
#: away from what the scenarios actually supply.
CANARIES: Final[tuple[str, ...]] = (
    ACCOUNT,
    OTHER_ACCOUNT,
    BUCKET,
    COMMIT,
    TREE,
    ENVELOPE,
    CURRENT,
    OTHER_USER,
)


def _document(**overrides: Any) -> dict[str, Any]:
    """A complete, valid synthetic binding document, with fields overridable."""
    document: dict[str, Any] = {
        "schema_version": rb.RUNTIME_BINDING_SCHEMA_VERSION,
        "binding_kind": rb.RUNTIME_BINDING_KIND,
        "contract_id": rb.RUNTIME_BINDING_CONTRACT_ID,
        "aws_partition": rb.EXPECTED_PARTITION,
        "aws_region": rb.EXPECTED_REGION,
        "target_account_id": ACCOUNT,
        "acquisition_profile": rb.EXPECTED_ACQUISITION_PROFILE,
        "licensed_bucket_name": BUCKET,
        "provenance": {
            "implementation_commit": COMMIT,
            "implementation_tree": TREE,
            "environment_binding_sha256": ENVELOPE,
        },
    }
    document.update(overrides)
    return document


def _encode(document: object) -> bytes:
    return json.dumps(document).encode("utf-8")


def _security(**overrides: Any) -> rb.FileSecurity:
    """A hardened synthetic security report: owned by us, protected, one entry."""
    fields: dict[str, Any] = {
        "current_principal": CURRENT,
        "owner": CURRENT,
        "inheritance_disabled": True,
        "allow_principals": (CURRENT,),
        "deny_principals": (),
    }
    fields.update(overrides)
    return rb.FileSecurity(**fields)


def _load(
    tmp_path: Path,
    *,
    raw: bytes | None = None,
    account: str | None = ACCOUNT,
    security: rb.FileSecurity | None = None,
    security_of: Callable[[Path], rb.FileSecurity] | None = None,
    path_override: str | None = None,
    root_override: Path | None = None,
) -> rb.QualificationRuntimeBinding:
    """Drive the loader against a synthetic private root inside ``tmp_path``."""
    root = tmp_path / "KalpaMani" / "private"
    root.mkdir(parents=True, exist_ok=True)
    target = root / "binding.json"
    if raw is None:
        raw = _encode(_document())
    target.write_bytes(raw)

    settled = security if security is not None else _security()
    inspect = security_of if security_of is not None else (lambda _path: settled)
    return rb.load_runtime_binding(
        expected_account=account,
        path_source=lambda: path_override if path_override is not None else str(target),
        root_source=lambda: root_override if root_override is not None else root,
        security_of=inspect,
    )


def _refused(tmp_path: Path, **kwargs: Any) -> pytest.ExceptionInfo[rb.RuntimeBindingError]:
    with pytest.raises(rb.RuntimeBindingError) as caught:
        _load(tmp_path, **kwargs)
    return caught


# -- the valid contract -------------------------------------------------------


def test_a_valid_synthetic_binding_is_accepted(tmp_path: Path) -> None:
    binding = _load(tmp_path)
    assert binding.licensed_bucket_name == BUCKET
    assert binding.partition == rb.EXPECTED_PARTITION
    assert binding.region == rb.EXPECTED_REGION
    assert binding.acquisition_profile == rb.EXPECTED_ACQUISITION_PROFILE


def test_the_validated_result_is_immutable_and_carries_no_account(tmp_path: Path) -> None:
    """Frozen, unsubclassable, and missing the one field a caller could print.

    The account is compared and dropped: the value never leaves the loader, so no
    caller can put it in a log line, and the identity gate one stage earlier is what
    actually proves the account.
    """
    binding = _load(tmp_path)
    with pytest.raises(AttributeError):
        binding.licensed_bucket_name = "other-bucket"  # type: ignore[misc]
    assert not hasattr(binding, "target_account_id")
    with pytest.raises(TypeError):

        class _Widened(rb.QualificationRuntimeBinding):
            pass


def test_the_result_repr_never_carries_the_bucket(tmp_path: Path) -> None:
    binding = _load(tmp_path)
    assert BUCKET not in repr(binding)
    assert rb.EXPECTED_REGION in repr(binding)


def test_the_security_report_repr_never_carries_a_principal() -> None:
    security = _security(allow_principals=(CURRENT,), deny_principals=())
    assert CURRENT not in repr(security)
    assert "allow=1" in repr(security)
    with pytest.raises(TypeError):

        class _Widened(rb.FileSecurity):
            pass


def test_loading_enumerates_no_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every listing primitive is replaced by a trap, and the load still succeeds.

    The private root is a containment boundary, not a search path: a loader that
    could list it would turn a wrong environment variable into a silent substitution
    of somebody else's private file.
    """

    def _trap(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("the loader enumerated a directory")

    monkeypatch.setattr(Path, "iterdir", _trap)
    monkeypatch.setattr(Path, "glob", _trap)
    monkeypatch.setattr(Path, "rglob", _trap)
    monkeypatch.setattr(os, "listdir", _trap)
    monkeypatch.setattr(os, "scandir", _trap)
    monkeypatch.setattr(os, "walk", _trap)
    assert _load(tmp_path).licensed_bucket_name == BUCKET


def test_loading_reads_exactly_one_file_and_only_the_selected_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    read: list[Path] = []
    original = Path.read_bytes

    def _record(self: Path) -> bytes:
        read.append(self)
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", _record)
    _load(tmp_path)
    assert len(read) == 1
    assert read[0] == tmp_path / "KalpaMani" / "private" / "binding.json"


def test_loading_spawns_no_process_and_opens_no_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No Terraform, no AWS CLI, no SDK -- the whole point of ADR-0023.

    Traps rather than assertions after the fact: a call that happened and was then
    counted has already left the machine.
    """

    def _trap(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("the loader reached a process or a socket")

    monkeypatch.setattr(subprocess, "run", _trap)
    monkeypatch.setattr(subprocess, "Popen", _trap)
    monkeypatch.setattr(socket, "socket", _trap)
    assert _load(tmp_path).licensed_bucket_name == BUCKET


def test_the_module_names_the_same_governed_literals_the_entry_point_pins() -> None:
    """One spelling of the profile and the region, checked rather than trusted."""
    source = (
        Path(__file__).resolve().parents[2] / "scripts" / "sharadar_empirical_qualification.py"
    ).read_text(encoding="utf-8")
    assert f'EXPECTED_PROFILE: Final = "{rb.EXPECTED_ACQUISITION_PROFILE}"' in source
    assert f'EXPECTED_REGION: Final = "{rb.EXPECTED_REGION}"' in source
    assert f'RUNTIME_BINDING_ENV_VAR: Final = "{rb.RUNTIME_BINDING_ENV_VAR}"' in source


def test_the_bucket_grammar_matches_every_other_spelling_in_the_repository() -> None:
    """Three copies of one pattern, and a test that would catch a drift.

    The store and the write-only publisher each spell it privately for the same
    reason this module does; an import between them would hide a divergence rather
    than reveal one.
    """
    from kalpamani.data.qualify.sharadar import publication
    from kalpamani.data.storage import s3

    assert rb._BUCKET_NAME.pattern == s3._BUCKET_NAME.pattern
    assert rb._BUCKET_NAME.pattern == publication._BUCKET_NAME.pattern


# -- the production path and root sources -------------------------------------


def test_the_production_path_source_reads_the_one_fixed_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(rb.RUNTIME_BINDING_ENV_VAR, r"C:\synthetic\binding.json")
    assert rb.environment_binding_path() == r"C:\synthetic\binding.json"


def test_the_production_path_source_refuses_an_unset_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(rb.RUNTIME_BINDING_ENV_VAR, raising=False)
    with pytest.raises(rb.RuntimeBindingError) as caught:
        rb.environment_binding_path()
    assert caught.value.defect is rb.RuntimeBindingDefect.ENVIRONMENT_UNSET


def test_the_production_path_source_refuses_a_blank_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(rb.RUNTIME_BINDING_ENV_VAR, "   ")
    with pytest.raises(rb.RuntimeBindingError) as caught:
        rb.environment_binding_path()
    assert caught.value.defect is rb.RuntimeBindingDefect.ENVIRONMENT_UNSET


def test_the_production_root_is_the_documented_private_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(rb.PRIVATE_ROOT_ENV_VAR, r"C:\synthetic\AppData\Local")
    assert rb.private_root() == Path(r"C:\synthetic\AppData\Local\KalpaMani\private")


@pytest.mark.parametrize("value", ["", "   ", "relative\\local"])
def test_the_production_root_refuses_an_unusable_local_application_data(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(rb.PRIVATE_ROOT_ENV_VAR, value)
    with pytest.raises(rb.RuntimeBindingError) as caught:
        rb.private_root()
    assert caught.value.defect is rb.RuntimeBindingDefect.PRIVATE_ROOT_UNRESOLVED


def test_a_root_source_that_is_not_an_absolute_path_refuses(tmp_path: Path) -> None:
    caught = _refused(tmp_path, root_override=Path("KalpaMani/private"))
    assert caught.value.defect is rb.RuntimeBindingDefect.PRIVATE_ROOT_UNRESOLVED


# -- path containment ---------------------------------------------------------


def test_a_blank_selected_path_refuses(tmp_path: Path) -> None:
    caught = _refused(tmp_path, path_override="   ")
    assert caught.value.defect is rb.RuntimeBindingDefect.ENVIRONMENT_UNSET


def test_a_relative_selected_path_refuses(tmp_path: Path) -> None:
    caught = _refused(tmp_path, path_override="KalpaMani\\private\\binding.json")
    assert caught.value.defect is rb.RuntimeBindingDefect.PATH_NOT_ABSOLUTE


def test_a_path_outside_the_private_root_refuses(tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere" / "binding.json"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_bytes(_encode(_document()))
    caught = _refused(tmp_path, path_override=str(outside))
    assert caught.value.defect is rb.RuntimeBindingDefect.PATH_OUTSIDE_PRIVATE_ROOT


def test_a_repository_local_path_refuses(tmp_path: Path) -> None:
    """A binding checked into the working tree is the outcome ADR-0023 forbids."""
    repository = Path(__file__).resolve().parents[2] / "pyproject.toml"
    caught = _refused(tmp_path, path_override=str(repository))
    assert caught.value.defect is rb.RuntimeBindingDefect.PATH_OUTSIDE_PRIVATE_ROOT


def test_the_private_root_itself_is_not_a_binding(tmp_path: Path) -> None:
    root = tmp_path / "KalpaMani" / "private"
    root.mkdir(parents=True, exist_ok=True)
    caught = _refused(tmp_path, path_override=str(root))
    assert caught.value.defect is rb.RuntimeBindingDefect.PATH_OUTSIDE_PRIVATE_ROOT


def test_a_canonical_path_escape_refuses(tmp_path: Path) -> None:
    """``..`` is removed lexically, and the result is measured against the boundary."""
    escape = tmp_path / "KalpaMani" / "private" / "sub" / ".." / ".." / "escape.json"
    caught = _refused(tmp_path, path_override=str(escape))
    assert caught.value.defect is rb.RuntimeBindingDefect.PATH_OUTSIDE_PRIVATE_ROOT


def test_a_directory_in_place_of_a_file_refuses(tmp_path: Path) -> None:
    directory = tmp_path / "KalpaMani" / "private" / "binding.d"
    directory.mkdir(parents=True, exist_ok=True)
    caught = _refused(tmp_path, path_override=str(directory))
    assert caught.value.defect is rb.RuntimeBindingDefect.PATH_NOT_A_REGULAR_FILE


def test_a_missing_file_refuses_before_anything_is_opened(tmp_path: Path) -> None:
    absent = tmp_path / "KalpaMani" / "private" / "absent.json"
    caught = _refused(tmp_path, path_override=str(absent))
    assert caught.value.defect is rb.RuntimeBindingDefect.PATH_NOT_A_REGULAR_FILE


def _stat_with(entry: os.stat_result, *, mode: int | None = None, attributes: int = 0) -> Any:
    """A stat result with one field replaced, for simulating a platform condition."""

    class _Simulated:
        st_mode = mode if mode is not None else entry.st_mode
        st_file_attributes = attributes
        st_dev = entry.st_dev
        st_ino = entry.st_ino
        st_size = entry.st_size
        st_mtime_ns = entry.st_mtime_ns

    return _Simulated()


def test_a_symlink_anywhere_in_the_chain_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulated at the ``lstat`` boundary, deliberately.

    Creating a real symlink on Windows needs a privilege this suite must not depend
    on, and a test that quietly skipped where the privilege is absent would be a test
    that never ran. The condition the loader actually reads is the mode returned by
    ``lstat``, so that is what is simulated -- the refusal path itself is real.
    """
    target = tmp_path / "KalpaMani" / "private" / "binding.json"
    original = Path.lstat

    def _lstat(self: Path) -> Any:
        entry = original(self)
        if self == target:
            plain = entry.st_mode & ~stat.S_IFMT(entry.st_mode)
            return _stat_with(entry, mode=plain | stat.S_IFLNK)
        return entry

    monkeypatch.setattr(Path, "lstat", _lstat)
    caught = _refused(tmp_path)
    assert caught.value.defect is rb.RuntimeBindingDefect.PATH_IS_A_LINK


def test_a_junction_or_reparse_point_in_the_chain_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reparse attribute is what distinguishes a junction, and it is honoured."""
    parent = tmp_path / "KalpaMani" / "private"
    original = Path.lstat
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))

    def _lstat(self: Path) -> Any:
        entry = original(self)
        if self == parent:
            return _stat_with(entry, attributes=reparse)
        return entry

    monkeypatch.setattr(Path, "lstat", _lstat)
    caught = _refused(tmp_path)
    assert caught.value.defect is rb.RuntimeBindingDefect.PATH_IS_A_LINK


def test_a_file_replaced_between_the_check_and_the_read_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The identity is taken before the read and confirmed after it."""
    target = tmp_path / "KalpaMani" / "private" / "binding.json"
    original = Path.read_bytes

    def _swap(self: Path) -> bytes:
        content = original(self)
        if self == target:
            # A different document, of a different length, written by somebody else
            # in the window between the ownership check and this read.
            self.write_bytes(_encode(_document(licensed_bucket_name="swapped-bucket-zz")))
        return content

    monkeypatch.setattr(Path, "read_bytes", _swap)
    caught = _refused(tmp_path)
    assert caught.value.defect is rb.RuntimeBindingDefect.FILE_CHANGED_DURING_READ


def test_security_that_changes_between_the_two_readings_refuses(tmp_path: Path) -> None:
    reports = [_security(), _security(allow_principals=(CURRENT, OTHER_USER))]

    def _changing(_path: Path) -> rb.FileSecurity:
        return reports.pop(0)

    caught = _refused(tmp_path, security_of=_changing)
    assert caught.value.defect is rb.RuntimeBindingDefect.FILE_CHANGED_DURING_READ


# -- ownership and the access control list ------------------------------------

ACL_FAILURES: Final[tuple[tuple[str, dict[str, Any], rb.RuntimeBindingDefect], ...]] = (
    (
        "another principal owns the file",
        {"owner": OTHER_USER},
        rb.RuntimeBindingDefect.OWNER_NOT_CURRENT_USER,
    ),
    (
        "the list is inherited",
        {"inheritance_disabled": False},
        rb.RuntimeBindingDefect.ACL_INHERITANCE_ENABLED,
    ),
    (
        "a second entry exists",
        {"allow_principals": (CURRENT, CURRENT)},
        rb.RuntimeBindingDefect.ACL_NOT_EXCLUSIVE,
    ),
    (
        "another user may reach it",
        {"allow_principals": (CURRENT, OTHER_USER)},
        rb.RuntimeBindingDefect.ACL_NOT_EXCLUSIVE,
    ),
    (
        "Administrators may reach it",
        {"allow_principals": (CURRENT, ADMINISTRATORS)},
        rb.RuntimeBindingDefect.ACL_NOT_EXCLUSIVE,
    ),
    (
        "SYSTEM may reach it",
        {"allow_principals": (CURRENT, SYSTEM)},
        rb.RuntimeBindingDefect.ACL_NOT_EXCLUSIVE,
    ),
    (
        "Users may reach it",
        {"allow_principals": (CURRENT, LOCAL_USERS)},
        rb.RuntimeBindingDefect.ACL_NOT_EXCLUSIVE,
    ),
    (
        "Authenticated Users may reach it",
        {"allow_principals": (CURRENT, AUTHENTICATED_USERS)},
        rb.RuntimeBindingDefect.ACL_NOT_EXCLUSIVE,
    ),
    (
        "Everyone may reach it",
        {"allow_principals": (CURRENT, EVERYONE)},
        rb.RuntimeBindingDefect.ACL_NOT_EXCLUSIVE,
    ),
    (
        "the only entry names somebody else",
        {"allow_principals": (OTHER_USER,)},
        rb.RuntimeBindingDefect.ACL_NOT_EXCLUSIVE,
    ),
    (
        "no entry names anybody",
        {"allow_principals": ()},
        rb.RuntimeBindingDefect.ACL_NOT_EXCLUSIVE,
    ),
    (
        "a deny entry names us",
        {"deny_principals": (CURRENT,)},
        rb.RuntimeBindingDefect.ACL_DENY_PRESENT,
    ),
    (
        "a deny entry names somebody else",
        {"deny_principals": (EVERYONE,)},
        rb.RuntimeBindingDefect.ACL_DENY_PRESENT,
    ),
    (
        "the platform reported no owner",
        {"owner": ""},
        rb.RuntimeBindingDefect.SECURITY_UNVERIFIABLE,
    ),
    (
        "the platform reported no current principal",
        {"current_principal": ""},
        rb.RuntimeBindingDefect.SECURITY_UNVERIFIABLE,
    ),
)


@pytest.mark.parametrize(
    ("overrides", "defect"),
    [(overrides, defect) for _label, overrides, defect in ACL_FAILURES],
    ids=[label for label, _overrides, _defect in ACL_FAILURES],
)
def test_an_unsafe_access_control_list_refuses(
    tmp_path: Path, overrides: dict[str, Any], defect: rb.RuntimeBindingDefect
) -> None:
    caught = _refused(tmp_path, security=_security(**overrides))
    assert caught.value.defect is defect


def test_a_platform_that_cannot_answer_refuses(tmp_path: Path) -> None:
    """Fail closed: an unverified boundary is not a satisfied boundary."""

    def _unavailable(_path: Path) -> rb.FileSecurity:
        raise rb.RuntimeBindingError(rb.RuntimeBindingDefect.SECURITY_UNVERIFIABLE)

    caught = _refused(tmp_path, security_of=_unavailable)
    assert caught.value.defect is rb.RuntimeBindingDefect.SECURITY_UNVERIFIABLE


def test_an_inspector_answering_with_the_wrong_type_refuses(tmp_path: Path) -> None:
    def _wrong(_path: Path) -> Any:
        return {"owner": CURRENT, "allow_principals": (CURRENT,)}

    caught = _refused(tmp_path, security_of=_wrong)
    assert caught.value.defect is rb.RuntimeBindingDefect.SECURITY_UNVERIFIABLE


def test_the_production_inspector_reads_a_real_file_and_fails_closed_on_a_missing_one(
    tmp_path: Path,
) -> None:
    """The real ctypes inspector, exercised end to end on a genuine file.

    The *policy* above it is driven synthetically everywhere else; this is the one
    place the platform call itself runs, so that ``SECURITY_UNVERIFIABLE`` means
    "the platform did not answer" rather than "nobody ever asked it".
    """
    probe = tmp_path / "probe.json"
    probe.write_bytes(b"{}")
    security = rb.windows_file_security(probe)
    assert security.owner.startswith("S-1-")
    assert security.current_principal.startswith("S-1-")
    assert all(principal.startswith("S-1-") for principal in security.allow_principals)
    assert isinstance(security.inheritance_disabled, bool)

    with pytest.raises(rb.RuntimeBindingError) as caught:
        rb.windows_file_security(tmp_path / "absent.json")
    assert caught.value.defect is rb.RuntimeBindingDefect.SECURITY_UNVERIFIABLE


# -- the file and its encoding ------------------------------------------------


def test_an_empty_file_refuses(tmp_path: Path) -> None:
    caught = _refused(tmp_path, raw=b"")
    assert caught.value.defect is rb.RuntimeBindingDefect.FILE_EMPTY


def test_an_oversized_file_refuses(tmp_path: Path) -> None:
    caught = _refused(tmp_path, raw=b" " * (rb.MAX_RUNTIME_BINDING_BYTES + 1))
    assert caught.value.defect is rb.RuntimeBindingDefect.FILE_TOO_LARGE


def test_invalid_utf8_refuses(tmp_path: Path) -> None:
    caught = _refused(tmp_path, raw=b'{"schema_version": 1, "x": "\xff\xfe"}')
    assert caught.value.defect is rb.RuntimeBindingDefect.ENCODING_INVALID


def test_a_byte_order_mark_refuses(tmp_path: Path) -> None:
    """Legal UTF-8, and still refused: one document must have one byte sequence."""
    caught = _refused(tmp_path, raw=b"\xef\xbb\xbf" + _encode(_document()))
    assert caught.value.defect is rb.RuntimeBindingDefect.ENCODING_INVALID


def test_malformed_json_refuses(tmp_path: Path) -> None:
    caught = _refused(tmp_path, raw=b'{"schema_version": 1,')
    assert caught.value.defect is rb.RuntimeBindingDefect.DOCUMENT_MALFORMED


@pytest.mark.parametrize("payload", [[], "text", 7, None, True])
def test_a_non_object_document_refuses(tmp_path: Path, payload: object) -> None:
    caught = _refused(tmp_path, raw=_encode(payload))
    assert caught.value.defect is rb.RuntimeBindingDefect.DOCUMENT_MALFORMED


def test_a_duplicate_top_level_key_refuses(tmp_path: Path) -> None:
    """The default decoder keeps the last occurrence, so this hook refuses instead."""
    document = json.dumps(_document())
    doubled = document[:-1] + f', "licensed_bucket_name": "{BUCKET}"' + "}"
    caught = _refused(tmp_path, raw=doubled.encode("utf-8"))
    assert caught.value.defect is rb.RuntimeBindingDefect.DUPLICATE_KEY


def test_a_duplicate_provenance_key_refuses(tmp_path: Path) -> None:
    document = json.dumps(_document())
    marker = f'"implementation_commit": "{COMMIT}"'
    assert marker in document
    doubled = document.replace(marker, f"{marker}, {marker}")
    caught = _refused(tmp_path, raw=doubled.encode("utf-8"))
    assert caught.value.defect is rb.RuntimeBindingDefect.DUPLICATE_KEY


# -- the document contract ----------------------------------------------------

DOCUMENT_FAILURES: Final[tuple[tuple[str, dict[str, Any], rb.RuntimeBindingDefect], ...]] = (
    (
        "an unknown top-level field",
        {"extra_field": "x"},
        rb.RuntimeBindingDefect.FIELD_UNKNOWN,
    ),
    (
        "a wrong schema version",
        {"schema_version": 2},
        rb.RuntimeBindingDefect.SCHEMA_VERSION_UNKNOWN,
    ),
    (
        "a non-integer schema version",
        {"schema_version": "1"},
        rb.RuntimeBindingDefect.FIELD_MALFORMED,
    ),
    (
        "a boolean schema version",
        {"schema_version": True},
        rb.RuntimeBindingDefect.FIELD_MALFORMED,
    ),
    (
        "a wrong binding kind",
        {"binding_kind": "kalpamani-something-else"},
        rb.RuntimeBindingDefect.BINDING_KIND_UNKNOWN,
    ),
    (
        "a non-string binding kind",
        {"binding_kind": 1},
        rb.RuntimeBindingDefect.FIELD_MALFORMED,
    ),
    (
        "a wrong contract identifier",
        {"contract_id": "qualification-runtime-binding/v2"},
        rb.RuntimeBindingDefect.CONTRACT_ID_UNKNOWN,
    ),
    (
        "a wrong partition",
        {"aws_partition": "aws-us-gov"},
        rb.RuntimeBindingDefect.PARTITION_UNEXPECTED,
    ),
    (
        "a wrong region",
        {"aws_region": "eu-west-1"},
        rb.RuntimeBindingDefect.REGION_UNEXPECTED,
    ),
    (
        "the assessment profile",
        {"acquisition_profile": "kalpamani-qualification-assessment"},
        rb.RuntimeBindingDefect.PROFILE_UNEXPECTED,
    ),
    (
        "the foundation profile",
        {"acquisition_profile": "kalpamani-foundation"},
        rb.RuntimeBindingDefect.PROFILE_UNEXPECTED,
    ),
    (
        "a short account",
        {"target_account_id": "00000000000"},
        rb.RuntimeBindingDefect.ACCOUNT_MALFORMED,
    ),
    (
        "a non-numeric account",
        {"target_account_id": "00000000000a"},
        rb.RuntimeBindingDefect.ACCOUNT_MALFORMED,
    ),
    (
        "a non-string account",
        {"target_account_id": 0},
        rb.RuntimeBindingDefect.FIELD_MALFORMED,
    ),
    (
        "another account",
        {"target_account_id": OTHER_ACCOUNT},
        rb.RuntimeBindingDefect.ACCOUNT_MISMATCH,
    ),
    (
        "a bucket ARN",
        {"licensed_bucket_name": f"arn:aws:s3:::{BUCKET}"},
        rb.RuntimeBindingDefect.BUCKET_NAME_MALFORMED,
    ),
    (
        "a bucket URI",
        {"licensed_bucket_name": f"s3://{BUCKET}"},
        rb.RuntimeBindingDefect.BUCKET_NAME_MALFORMED,
    ),
    (
        "an uppercase bucket",
        {"licensed_bucket_name": BUCKET.upper()},
        rb.RuntimeBindingDefect.BUCKET_NAME_MALFORMED,
    ),
    (
        "a non-string bucket",
        {"licensed_bucket_name": None},
        rb.RuntimeBindingDefect.FIELD_MALFORMED,
    ),
    (
        "provenance that is not an object",
        {"provenance": [COMMIT, TREE, ENVELOPE]},
        rb.RuntimeBindingDefect.PROVENANCE_MALFORMED,
    ),
    (
        "an extra provenance field",
        {
            "provenance": {
                "implementation_commit": COMMIT,
                "implementation_tree": TREE,
                "environment_binding_sha256": ENVELOPE,
                "operator": "someone",
            }
        },
        rb.RuntimeBindingDefect.FIELD_UNKNOWN,
    ),
    (
        "a missing provenance field",
        {
            "provenance": {
                "implementation_commit": COMMIT,
                "implementation_tree": TREE,
            }
        },
        rb.RuntimeBindingDefect.FIELD_MISSING,
    ),
    (
        "an uppercase commit",
        {
            "provenance": {
                "implementation_commit": COMMIT.upper(),
                "implementation_tree": TREE,
                "environment_binding_sha256": ENVELOPE,
            }
        },
        rb.RuntimeBindingDefect.PROVENANCE_MALFORMED,
    ),
    (
        "a short tree",
        {
            "provenance": {
                "implementation_commit": COMMIT,
                "implementation_tree": TREE[:-1],
                "environment_binding_sha256": ENVELOPE,
            }
        },
        rb.RuntimeBindingDefect.PROVENANCE_MALFORMED,
    ),
    (
        "a forty-character envelope digest",
        {
            "provenance": {
                "implementation_commit": COMMIT,
                "implementation_tree": TREE,
                "environment_binding_sha256": COMMIT,
            }
        },
        rb.RuntimeBindingDefect.PROVENANCE_MALFORMED,
    ),
    (
        "a non-string provenance value",
        {
            "provenance": {
                "implementation_commit": COMMIT,
                "implementation_tree": TREE,
                "environment_binding_sha256": 0,
            }
        },
        rb.RuntimeBindingDefect.PROVENANCE_MALFORMED,
    ),
)


@pytest.mark.parametrize(
    ("overrides", "defect"),
    [(overrides, defect) for _label, overrides, defect in DOCUMENT_FAILURES],
    ids=[label for label, _overrides, _defect in DOCUMENT_FAILURES],
)
def test_a_document_breaking_the_contract_refuses(
    tmp_path: Path, overrides: dict[str, Any], defect: rb.RuntimeBindingDefect
) -> None:
    caught = _refused(tmp_path, raw=_encode(_document(**overrides)))
    assert caught.value.defect is defect


@pytest.mark.parametrize("missing", sorted(rb._DOCUMENT_FIELDS))
def test_every_missing_top_level_field_refuses(tmp_path: Path, missing: str) -> None:
    document = _document()
    del document[missing]
    caught = _refused(tmp_path, raw=_encode(document))
    assert caught.value.defect is rb.RuntimeBindingDefect.FIELD_MISSING


# -- the governed expected account --------------------------------------------


@pytest.mark.parametrize("supplied", [None, "", "not-an-account", "00000000000", 0])
def test_an_unusable_expected_account_refuses(tmp_path: Path, supplied: Any) -> None:
    """The caller could not establish the governed account, so nothing is admitted.

    ``expected_account`` answers ``None`` when the local binding is absent, and a
    loader that treated that as "no comparison needed" would admit a binding for any
    account at all.
    """
    caught = _refused(tmp_path, account=supplied)
    assert caught.value.defect is rb.RuntimeBindingDefect.EXPECTED_ACCOUNT_UNAVAILABLE


def test_the_document_parser_reads_no_file(tmp_path: Path) -> None:
    """``parse_runtime_binding`` is pure, which is why every rule above is testable."""
    binding = rb.parse_runtime_binding(_document(), expected_account=ACCOUNT)
    assert binding.licensed_bucket_name == BUCKET
    assert not any(tmp_path.iterdir())


# -- nothing leaks ------------------------------------------------------------

LEAK_SCENARIOS: Final[tuple[tuple[str, dict[str, Any]], ...]] = (
    ("an unsafe path", {"path_override": r"C:\elsewhere\binding.json"}),
    ("a relative path", {"path_override": "binding.json"}),
    ("an inherited list", {"security": _security(inheritance_disabled=False)}),
    ("a shared list", {"security": _security(allow_principals=(CURRENT, EVERYONE))}),
    ("another owner", {"security": _security(owner=OTHER_USER)}),
    ("an oversized file", {"raw": b" " * (rb.MAX_RUNTIME_BINDING_BYTES + 1)}),
    ("malformed json", {"raw": b'{"licensed_bucket_name": "' + BUCKET.encode() + b'"'}),
    ("an unknown field", {"raw": _encode(_document(extra_field=BUCKET))}),
    ("another account", {"raw": _encode(_document(target_account_id=OTHER_ACCOUNT))}),
    ("a bucket arn", {"raw": _encode(_document(licensed_bucket_name=f"arn:aws:s3:::{BUCKET}"))}),
    ("a bad digest", {"raw": _encode(_document(provenance={"implementation_commit": COMMIT}))}),
    ("no governed account", {"account": None}),
)


@pytest.mark.parametrize(
    "kwargs",
    [kwargs for _label, kwargs in LEAK_SCENARIOS],
    ids=[label for label, _kwargs in LEAK_SCENARIOS],
)
def test_no_refusal_carries_a_private_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kwargs: dict[str, Any]
) -> None:
    """A refusal names the rule. Never the path, the account, the bucket or a digest.

    Both reprs, the string form and everything the loader printed, because a value
    that reaches any one of them reaches a transcript somebody pastes into a chat.
    """
    caught = _refused(tmp_path, **kwargs)
    printed = capsys.readouterr()
    surfaces = (
        str(caught.value),
        repr(caught.value),
        repr(caught.value.defect),
        printed.out,
        printed.err,
    )
    for surface in surfaces:
        for canary in CANARIES:
            assert canary not in surface
        assert str(tmp_path) not in surface
        assert "binding.json" not in surface
    assert printed.out == ""
    assert printed.err == ""
    assert str(caught.value) == caught.value.defect.value


def test_the_defect_vocabulary_carries_no_value_shaped_member() -> None:
    """Every member is a rule name: upper case, underscores, and nothing else."""
    for defect in rb.RuntimeBindingDefect:
        assert defect.value == defect.name
        assert defect.value.replace("_", "").isalpha()
        assert defect.value.isupper()


def test_a_defect_must_be_an_exact_member() -> None:
    with pytest.raises(TypeError):
        rb.RuntimeBindingError("ENVIRONMENT_UNSET")  # type: ignore[arg-type]
