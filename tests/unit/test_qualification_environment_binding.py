"""The governed environment binding, its producer, and the gate it feeds (ADR-0024).

ADR-0023 required ``provenance.environment_binding_sha256`` in the private runtime
binding and validated it as sixty-four lowercase hex characters. Nothing said what
those bytes were: no schema named the artifact, no producer wrote one, no
path-discovery mechanism selected one, and no code handed a digest to a
runtime-binding materialization that also did not exist. Sixty-four hex characters
that mean nothing in particular are a field somebody fills in, not provenance.

What is checked here:

**The contract.** A synthetic environment binding is driven through the production
validator -- every trust-boundary clause, every field rule, and the digest -- with an
injected security inspector and a synthetic private root. **Nothing here reimplements
a production rule**: the tests build documents and ask the real validator, and a scan
below refuses a grammar of this file's own.

**The producer and the gate.** Both operator commands are driven with injected
dependencies that count what they were asked for, so "no AWS call", "no Terraform" and
"one atomic create" are observations rather than claims.

**The isolation.** The capture is the only thing that may read governed infrastructure
outputs, and it must be unreachable from the acquisition run. The materialization gate
must reach no Terraform name at all.

**The mutations.** Four properties are removed in memory -- the digest binding, the
account consistency, the ACL verification and the call-graph isolation -- and each
guard is watched failing. A guard nobody has watched fail is a guard nobody has
tested.

**Every identifier is invented.** No real account, bucket, path, principal or
deployment value appears, and no real private artifact is created or read.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import socket
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest

from kalpamani.data.qualify.sharadar import runtime_binding as rb

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
SCRIPTS: Final = PROJECT_ROOT / "scripts"
WRITER_PATH: Final = SCRIPTS / "qualification_private_artifacts.py"
CAPTURE_PATH: Final = SCRIPTS / "qualification_environment_binding_capture.py"
MATERIALIZE_PATH: Final = SCRIPTS / "qualification_runtime_binding_materialize.py"
ACQUIRE_PATH: Final = SCRIPTS / "sharadar_empirical_qualification.py"

#: Synthetic, and matching no deployment. A twelve-digit run of zeroes is not an
#: account anybody holds, and the bucket names itself.
ACCOUNT: Final = "000000000000"
OTHER_ACCOUNT: Final = "999999999999"
BUCKET: Final = "synthetic-licensed-bucket-zz"
OTHER_BUCKET: Final = "synthetic-licensed-bucket-yy"
CURRENT: Final = "S-1-5-21-0-0-0-1001"
OTHER_USER: Final = "S-1-5-21-0-0-0-1002"
EVERYONE: Final = "S-1-1-0"
CAPTURED_AT: Final = "2000-01-01T00:00:00Z"
OUTPUTS_DIGEST: Final = "0123456789abcdef" * 4
COMMIT: Final = "0123456789abcdef0123456789abcdef01234567"
TREE: Final = "89abcdef0123456789abcdef0123456789abcdef"


def _load_script(name: str, path: Path) -> ModuleType:
    """One operator script, loaded from its file under a test-only module name."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


writer = _load_script("_private_artifacts_under_test", WRITER_PATH)
capture = _load_script("_environment_capture_under_test", CAPTURE_PATH)
materialize = _load_script("_runtime_materialize_under_test", MATERIALIZE_PATH)


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------


def _environment_document(**overrides: Any) -> dict[str, Any]:
    """A well-formed synthetic environment binding, built from production constants."""
    document: dict[str, Any] = {
        "schema_version": rb.ENVIRONMENT_BINDING_SCHEMA_VERSION,
        "binding_kind": rb.ENVIRONMENT_BINDING_KIND,
        "contract_id": rb.ENVIRONMENT_BINDING_CONTRACT_ID,
        "aws_partition": rb.EXPECTED_PARTITION,
        "aws_region": rb.EXPECTED_REGION,
        "target_account_id": ACCOUNT,
        "licensed_bucket_name": BUCKET,
        "provenance": {
            "source_kind": rb.ENVIRONMENT_BINDING_SOURCE_KIND,
            "captured_at_utc": CAPTURED_AT,
            "outputs_digest": OUTPUTS_DIGEST,
        },
    }
    document.update(overrides)
    return document


def _runtime_document(**overrides: Any) -> dict[str, Any]:
    """A well-formed synthetic runtime binding, built from production constants."""
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
            "environment_binding_sha256": OUTPUTS_DIGEST,
        },
    }
    document.update(overrides)
    return document


def _security(**overrides: Any) -> rb.FileSecurity:
    """An owner-only security report, unless a test asks for something else."""
    settled: dict[str, Any] = {
        "current_principal": CURRENT,
        "owner": CURRENT,
        "inheritance_disabled": True,
        "allow_principals": (CURRENT,),
        "deny_principals": (),
    }
    settled.update(overrides)
    return rb.FileSecurity(**settled)


def _private_root(tmp_path: Path) -> Path:
    root = tmp_path / "KalpaMani" / "private"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _load_environment(
    tmp_path: Path,
    *,
    raw: bytes | None = None,
    account: str | None = ACCOUNT,
    security: rb.FileSecurity | None = None,
    security_of: Callable[[Path], rb.FileSecurity] | None = None,
    path_override: str | None = None,
    root_override: Path | None = None,
) -> rb.QualificationEnvironmentBinding:
    """Drive the production loader against a synthetic private root."""
    root = _private_root(tmp_path)
    target = root / "environment.json"
    if raw is None:
        raw = rb.canonical_binding_bytes(_environment_document())
    target.write_bytes(raw)

    settled = security if security is not None else _security()
    inspect = security_of if security_of is not None else (lambda _path: settled)
    return rb.load_environment_binding(
        path=path_override if path_override is not None else str(target),
        expected_account=account,
        root_source=lambda: root_override if root_override is not None else root,
        security_of=inspect,
    )


def _refused(tmp_path: Path, **kwargs: Any) -> pytest.ExceptionInfo[rb.RuntimeBindingError]:
    with pytest.raises(rb.RuntimeBindingError) as caught:
        _load_environment(tmp_path, **kwargs)
    return caught


# ---------------------------------------------------------------------------
# The contract the runtime binding's digest field now names
# ---------------------------------------------------------------------------


def test_a_valid_synthetic_environment_binding_is_accepted(tmp_path: Path) -> None:
    binding = _load_environment(tmp_path)
    assert binding.licensed_bucket_name == BUCKET
    assert binding.target_account_id == ACCOUNT
    assert binding.partition == rb.EXPECTED_PARTITION
    assert binding.region == rb.EXPECTED_REGION


def test_the_digest_is_of_the_exact_bytes_that_were_read(tmp_path: Path) -> None:
    """The field means bytes, which is the whole correction.

    A digest recomputed from the parsed document would name a *shape*: two files with
    different formatting would carry the same value, and a reviewer handed the digest
    could not re-derive it from the artifact.
    """
    raw = rb.canonical_binding_bytes(_environment_document())
    binding = _load_environment(tmp_path, raw=raw)
    assert binding.digest == rb.sha256_hex(raw)


def test_a_reserialisation_would_not_have_produced_that_digest(tmp_path: Path) -> None:
    """A differently formatted file with identical content digests differently."""
    document = _environment_document()
    spaced = (json.dumps(document, sort_keys=True, indent=2) + "\n").encode("utf-8")
    canonical = rb.canonical_binding_bytes(document)
    assert spaced != canonical

    binding = _load_environment(tmp_path, raw=spaced)
    assert binding.digest == rb.sha256_hex(spaced)
    assert binding.digest != rb.sha256_hex(canonical)


def test_the_result_repr_carries_no_account_bucket_or_digest(tmp_path: Path) -> None:
    rendered = repr(_load_environment(tmp_path))
    for private in (
        ACCOUNT,
        BUCKET,
        rb.sha256_hex(rb.canonical_binding_bytes(_environment_document())),
    ):
        assert private not in rendered


def test_the_result_is_immutable_and_refuses_subclassing(tmp_path: Path) -> None:
    binding = _load_environment(tmp_path)
    with pytest.raises(AttributeError):
        binding.licensed_bucket_name = OTHER_BUCKET  # type: ignore[misc]
    with pytest.raises(TypeError):

        class _Wider(rb.QualificationEnvironmentBinding):  # pragma: no cover - refused
            pass


def test_the_two_binding_kinds_cannot_be_confused(tmp_path: Path) -> None:
    """Neither artifact validates as the other, so a swapped path is refused."""
    caught = _refused(tmp_path, raw=rb.canonical_binding_bytes(_runtime_document()))
    assert caught.value.defect is rb.RuntimeBindingDefect.FIELD_UNKNOWN

    with pytest.raises(rb.RuntimeBindingError) as reverse:
        rb.parse_runtime_binding(_environment_document(), expected_account=ACCOUNT)
    assert reverse.value.defect is rb.RuntimeBindingDefect.FIELD_MISSING


# -- path selection and containment -------------------------------------------


def test_the_loader_takes_its_path_only_as_an_argument() -> None:
    """No environment lookup exists here, which is what keeps Run A away from it.

    Read out of the signature rather than by substring: a parameter is a fact about
    the function, and the acquisition path cannot supply one it never calls.
    """
    import inspect as introspection

    parameters = introspection.signature(rb.load_environment_binding).parameters
    assert "path" in parameters
    assert parameters["path"].default is introspection.Parameter.empty


def test_a_missing_environment_binding_refuses(tmp_path: Path) -> None:
    root = _private_root(tmp_path)
    caught = _refused(tmp_path, path_override=str(root / "absent.json"))
    assert caught.value.defect is rb.RuntimeBindingDefect.PATH_NOT_A_REGULAR_FILE


def test_a_relative_path_refuses(tmp_path: Path) -> None:
    caught = _refused(tmp_path, path_override="environment.json")
    assert caught.value.defect is rb.RuntimeBindingDefect.PATH_NOT_ABSOLUTE


def test_a_blank_path_refuses(tmp_path: Path) -> None:
    caught = _refused(tmp_path, path_override="   ")
    assert caught.value.defect is rb.RuntimeBindingDefect.ENVIRONMENT_UNSET


def test_a_path_outside_the_private_root_refuses(tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere.json"
    outside.write_bytes(rb.canonical_binding_bytes(_environment_document()))
    caught = _refused(tmp_path, path_override=str(outside))
    assert caught.value.defect is rb.RuntimeBindingDefect.PATH_OUTSIDE_PRIVATE_ROOT


def test_a_canonical_escape_out_of_the_private_root_refuses(tmp_path: Path) -> None:
    root = _private_root(tmp_path)
    caught = _refused(tmp_path, path_override=str(root / ".." / ".." / "escaped.json"))
    assert caught.value.defect is rb.RuntimeBindingDefect.PATH_OUTSIDE_PRIVATE_ROOT


def test_a_directory_in_place_of_the_artifact_refuses(tmp_path: Path) -> None:
    root = _private_root(tmp_path)
    (root / "folder").mkdir()
    caught = _refused(tmp_path, path_override=str(root / "folder"))
    assert caught.value.defect is rb.RuntimeBindingDefect.PATH_NOT_A_REGULAR_FILE


def _stat_with(entry: os.stat_result, *, mode: int | None = None, attributes: int = 0) -> Any:
    """One stat result with its mode or reparse attribute rewritten."""

    class _Rewritten:
        st_mode = mode if mode is not None else entry.st_mode
        st_dev = entry.st_dev
        st_ino = entry.st_ino
        st_size = entry.st_size
        st_mtime_ns = entry.st_mtime_ns
        st_file_attributes = attributes

    return _Rewritten()


def test_a_symlink_in_the_chain_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _private_root(tmp_path)
    target = root / "environment.json"
    target.write_bytes(rb.canonical_binding_bytes(_environment_document()))
    original = Path.lstat

    def _linked(self: Path) -> Any:
        entry = original(self)
        if self == target:
            return _stat_with(entry, mode=(entry.st_mode & ~stat.S_IFREG) | stat.S_IFLNK)
        return entry

    monkeypatch.setattr(Path, "lstat", _linked)
    with pytest.raises(rb.RuntimeBindingError) as caught:
        rb.load_environment_binding(
            path=str(target),
            expected_account=ACCOUNT,
            root_source=lambda: root,
            security_of=lambda _path: _security(),
        )
    assert caught.value.defect is rb.RuntimeBindingDefect.PATH_IS_A_LINK


def test_a_reparse_point_in_the_chain_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _private_root(tmp_path)
    target = root / "environment.json"
    target.write_bytes(rb.canonical_binding_bytes(_environment_document()))
    original = Path.lstat
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))

    def _junction(self: Path) -> Any:
        entry = original(self)
        if self == target:
            return _stat_with(entry, attributes=reparse)
        return entry

    monkeypatch.setattr(Path, "lstat", _junction)
    with pytest.raises(rb.RuntimeBindingError) as caught:
        rb.load_environment_binding(
            path=str(target),
            expected_account=ACCOUNT,
            root_source=lambda: root,
            security_of=lambda _path: _security(),
        )
    assert caught.value.defect is rb.RuntimeBindingDefect.PATH_IS_A_LINK


def test_loading_enumerates_no_private_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every listing primitive is a trap, and the load still succeeds."""

    def _trap(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("the loader enumerated a directory")

    monkeypatch.setattr(Path, "iterdir", _trap)
    monkeypatch.setattr(Path, "glob", _trap)
    monkeypatch.setattr(Path, "rglob", _trap)
    monkeypatch.setattr(os, "listdir", _trap)
    monkeypatch.setattr(os, "scandir", _trap)
    monkeypatch.setattr(os, "walk", _trap)
    assert _load_environment(tmp_path).licensed_bucket_name == BUCKET


# -- ownership and the access control list ------------------------------------

ACL_FAILURES: Final[tuple[tuple[str, dict[str, Any], rb.RuntimeBindingDefect], ...]] = (
    (
        "another principal owns it",
        {"owner": OTHER_USER},
        rb.RuntimeBindingDefect.OWNER_NOT_CURRENT_USER,
    ),
    (
        "the list is inherited",
        {"inheritance_disabled": False},
        rb.RuntimeBindingDefect.ACL_INHERITANCE_ENABLED,
    ),
    (
        "a second principal may reach it",
        {"allow_principals": (CURRENT, OTHER_USER)},
        rb.RuntimeBindingDefect.ACL_NOT_EXCLUSIVE,
    ),
    (
        "everyone may reach it",
        {"allow_principals": (CURRENT, EVERYONE)},
        rb.RuntimeBindingDefect.ACL_NOT_EXCLUSIVE,
    ),
    (
        "a deny entry exists",
        {"deny_principals": (EVERYONE,)},
        rb.RuntimeBindingDefect.ACL_DENY_PRESENT,
    ),
    (
        "the platform reported no owner",
        {"owner": ""},
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


def test_a_security_query_that_cannot_be_answered_refuses(tmp_path: Path) -> None:
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


def test_security_that_changes_between_the_two_readings_refuses(tmp_path: Path) -> None:
    reports = [_security(), _security(allow_principals=(CURRENT, OTHER_USER))]

    def _changing(_path: Path) -> rb.FileSecurity:
        return reports.pop(0)

    caught = _refused(tmp_path, security_of=_changing)
    assert caught.value.defect is rb.RuntimeBindingDefect.FILE_CHANGED_DURING_READ


def test_a_file_replaced_between_the_check_and_the_read_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _private_root(tmp_path)
    target = root / "environment.json"
    target.write_bytes(rb.canonical_binding_bytes(_environment_document()))
    original = Path.read_bytes

    def _swapping(self: Path) -> bytes:
        content = original(self)
        self.write_bytes(
            rb.canonical_binding_bytes(_environment_document(licensed_bucket_name=OTHER_BUCKET))
        )
        return content

    monkeypatch.setattr(Path, "read_bytes", _swapping)
    with pytest.raises(rb.RuntimeBindingError) as caught:
        rb.load_environment_binding(
            path=str(target),
            expected_account=ACCOUNT,
            root_source=lambda: root,
            security_of=lambda _path: _security(),
        )
    assert caught.value.defect is rb.RuntimeBindingDefect.FILE_CHANGED_DURING_READ


# -- the file, its encoding and its fields ------------------------------------


def test_an_empty_environment_binding_refuses(tmp_path: Path) -> None:
    caught = _refused(tmp_path, raw=b"")
    assert caught.value.defect is rb.RuntimeBindingDefect.FILE_EMPTY


def test_an_oversized_environment_binding_refuses(tmp_path: Path) -> None:
    padded = b"{" + b" " * (rb.MAX_ENVIRONMENT_BINDING_BYTES + 1) + b"}"
    caught = _refused(tmp_path, raw=padded)
    assert caught.value.defect is rb.RuntimeBindingDefect.FILE_TOO_LARGE


def test_a_byte_order_mark_refuses(tmp_path: Path) -> None:
    marked = bytes((0xEF, 0xBB, 0xBF)) + rb.canonical_binding_bytes(_environment_document())
    caught = _refused(tmp_path, raw=marked)
    assert caught.value.defect is rb.RuntimeBindingDefect.ENCODING_INVALID


def test_invalid_utf8_refuses(tmp_path: Path) -> None:
    caught = _refused(tmp_path, raw=bytes((0x7B, 0xFF, 0x7D)))
    assert caught.value.defect is rb.RuntimeBindingDefect.ENCODING_INVALID


def test_malformed_json_refuses(tmp_path: Path) -> None:
    caught = _refused(tmp_path, raw=b"{not json")
    assert caught.value.defect is rb.RuntimeBindingDefect.DOCUMENT_MALFORMED


def test_a_non_object_document_refuses(tmp_path: Path) -> None:
    caught = _refused(tmp_path, raw=b"[1, 2, 3]")
    assert caught.value.defect is rb.RuntimeBindingDefect.DOCUMENT_MALFORMED


def test_a_duplicate_top_level_key_refuses(tmp_path: Path) -> None:
    document = rb.canonical_binding_bytes(_environment_document()).decode("utf-8").rstrip("\n")
    duplicated = (document[:-1] + ',"licensed_bucket_name":"' + OTHER_BUCKET + '"}').encode("utf-8")
    caught = _refused(tmp_path, raw=duplicated)
    assert caught.value.defect is rb.RuntimeBindingDefect.DUPLICATE_KEY


def test_a_duplicate_provenance_key_refuses(tmp_path: Path) -> None:
    text = rb.canonical_binding_bytes(_environment_document()).decode("utf-8")
    duplicated = text.replace(
        '"source_kind"', '"outputs_digest":"' + OUTPUTS_DIGEST + '","source_kind"', 1
    ).encode("utf-8")
    caught = _refused(tmp_path, raw=duplicated)
    assert caught.value.defect is rb.RuntimeBindingDefect.DUPLICATE_KEY


DOCUMENT_FAILURES: Final[tuple[tuple[str, dict[str, Any], rb.RuntimeBindingDefect], ...]] = (
    ("an extra top-level field", {"extra": 1}, rb.RuntimeBindingDefect.FIELD_UNKNOWN),
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
        "another binding kind",
        {"binding_kind": rb.RUNTIME_BINDING_KIND},
        rb.RuntimeBindingDefect.BINDING_KIND_UNKNOWN,
    ),
    (
        "another contract",
        {"contract_id": rb.RUNTIME_BINDING_CONTRACT_ID},
        rb.RuntimeBindingDefect.CONTRACT_ID_UNKNOWN,
    ),
    (
        "another partition",
        {"aws_partition": "aws-us-gov"},
        rb.RuntimeBindingDefect.PARTITION_UNEXPECTED,
    ),
    ("another region", {"aws_region": "eu-west-1"}, rb.RuntimeBindingDefect.REGION_UNEXPECTED),
    (
        "an account that is not twelve digits",
        {"target_account_id": "12345"},
        rb.RuntimeBindingDefect.ACCOUNT_MALFORMED,
    ),
    (
        "an account of the wrong type",
        {"target_account_id": 123456789012},
        rb.RuntimeBindingDefect.FIELD_MALFORMED,
    ),
    (
        "another deployment's account",
        {"target_account_id": OTHER_ACCOUNT},
        rb.RuntimeBindingDefect.ACCOUNT_MISMATCH,
    ),
    (
        "a bucket that is an ARN",
        {"licensed_bucket_name": "arn:aws:s3:::" + BUCKET},
        rb.RuntimeBindingDefect.BUCKET_NAME_MALFORMED,
    ),
    (
        "a bucket that is a URI",
        {"licensed_bucket_name": "s3://" + BUCKET},
        rb.RuntimeBindingDefect.BUCKET_NAME_MALFORMED,
    ),
    (
        "a bucket of the wrong type",
        {"licensed_bucket_name": None},
        rb.RuntimeBindingDefect.FIELD_MALFORMED,
    ),
    (
        "provenance that is not an object",
        {"provenance": []},
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
    caught = _refused(tmp_path, raw=rb.canonical_binding_bytes(_environment_document(**overrides)))
    assert caught.value.defect is defect


@pytest.mark.parametrize("missing", sorted(rb._ENVIRONMENT_FIELDS))
def test_every_missing_top_level_field_refuses(tmp_path: Path, missing: str) -> None:
    document = _environment_document()
    del document[missing]
    caught = _refused(tmp_path, raw=rb.canonical_binding_bytes(document))
    assert caught.value.defect is rb.RuntimeBindingDefect.FIELD_MISSING


PROVENANCE_FAILURES: Final[tuple[tuple[str, dict[str, Any], rb.RuntimeBindingDefect], ...]] = (
    ("an unknown provenance field", {"extra": 1}, rb.RuntimeBindingDefect.FIELD_UNKNOWN),
    (
        "another capture mechanism",
        {"source_kind": "hand-written"},
        rb.RuntimeBindingDefect.PROVENANCE_MALFORMED,
    ),
    (
        "an instant with an offset instead of Z",
        {"captured_at_utc": "2000-01-01T00:00:00+00:00"},
        rb.RuntimeBindingDefect.PROVENANCE_MALFORMED,
    ),
    (
        "an instant that is not a timestamp",
        {"captured_at_utc": "yesterday"},
        rb.RuntimeBindingDefect.PROVENANCE_MALFORMED,
    ),
    (
        "an outputs digest of the wrong length",
        {"outputs_digest": OUTPUTS_DIGEST[:-1]},
        rb.RuntimeBindingDefect.PROVENANCE_MALFORMED,
    ),
    (
        "an outputs digest in upper case",
        {"outputs_digest": OUTPUTS_DIGEST.upper()},
        rb.RuntimeBindingDefect.PROVENANCE_MALFORMED,
    ),
    (
        "an outputs digest of the wrong type",
        {"outputs_digest": 0},
        rb.RuntimeBindingDefect.PROVENANCE_MALFORMED,
    ),
)


@pytest.mark.parametrize(
    ("overrides", "defect"),
    [(overrides, defect) for _label, overrides, defect in PROVENANCE_FAILURES],
    ids=[label for label, _overrides, _defect in PROVENANCE_FAILURES],
)
def test_malformed_provenance_refuses(
    tmp_path: Path, overrides: dict[str, Any], defect: rb.RuntimeBindingDefect
) -> None:
    provenance = dict(_environment_document()["provenance"])
    provenance.update(overrides)
    caught = _refused(
        tmp_path, raw=rb.canonical_binding_bytes(_environment_document(provenance=provenance))
    )
    assert caught.value.defect is defect


@pytest.mark.parametrize("missing", sorted(rb._ENVIRONMENT_PROVENANCE_FIELDS))
def test_every_missing_provenance_field_refuses(tmp_path: Path, missing: str) -> None:
    provenance = dict(_environment_document()["provenance"])
    del provenance[missing]
    caught = _refused(
        tmp_path, raw=rb.canonical_binding_bytes(_environment_document(provenance=provenance))
    )
    assert caught.value.defect is rb.RuntimeBindingDefect.FIELD_MISSING


@pytest.mark.parametrize("supplied", [None, "", "1234", "00000000000o", "0000000000000"])
def test_an_unusable_expected_account_refuses(tmp_path: Path, supplied: Any) -> None:
    caught = _refused(tmp_path, account=supplied)
    assert caught.value.defect is rb.RuntimeBindingDefect.EXPECTED_ACCOUNT_UNAVAILABLE


def test_an_expected_account_of_the_wrong_type_refuses(tmp_path: Path) -> None:
    """Twelve digits as an integer passes the grammar and then cannot compare equal.

    The grammar is applied to ``str(expected_account)``, so an integer reaches the
    comparison -- where it is never equal to the document's string. It fails closed,
    with the mismatch rather than the availability defect, and this records which.
    """
    caught = _refused(tmp_path, account=123456789012)
    assert caught.value.defect is rb.RuntimeBindingDefect.ACCOUNT_MISMATCH


@pytest.mark.parametrize("supplied", [None, "", OUTPUTS_DIGEST[:-1], OUTPUTS_DIGEST.upper(), 0])
def test_a_digest_the_parser_cannot_trust_refuses(supplied: Any) -> None:
    with pytest.raises(rb.RuntimeBindingError) as caught:
        rb.parse_environment_binding(
            _environment_document(), expected_account=ACCOUNT, digest=supplied
        )
    assert caught.value.defect is rb.RuntimeBindingDefect.PROVENANCE_MALFORMED


def test_the_document_parser_reads_no_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """The rules are testable with no filesystem at all, which is how they are tested."""

    def _trap(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("the parser opened something")

    monkeypatch.setattr(Path, "read_bytes", _trap)
    monkeypatch.setattr(Path, "read_text", _trap)
    monkeypatch.setattr(os, "open", _trap)
    binding = rb.parse_environment_binding(
        _environment_document(), expected_account=ACCOUNT, digest=OUTPUTS_DIGEST
    )
    assert binding.digest == OUTPUTS_DIGEST


PRIVATE_CANARIES: Final[tuple[str, ...]] = (ACCOUNT, BUCKET, CURRENT, OUTPUTS_DIGEST)


@pytest.mark.parametrize(
    "overrides",
    [
        {"raw": b"{not json"},
        {"account": OTHER_ACCOUNT},
        {"security": _security(owner=OTHER_USER)},
        {"raw": rb.canonical_binding_bytes(_environment_document(aws_region="eu-west-1"))},
    ],
    ids=["malformed", "another account", "another owner", "another region"],
)
def test_no_refusal_carries_a_private_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], overrides: dict[str, Any]
) -> None:
    caught = _refused(tmp_path, **overrides)
    captured = capsys.readouterr()
    surfaces = (str(caught.value), repr(caught.value), captured.out, captured.err)
    for canary in PRIVATE_CANARIES:
        for surface in surfaces:
            assert canary not in surface


# ---------------------------------------------------------------------------
# The one private-artifact writer
# ---------------------------------------------------------------------------


class _Descriptor:
    """A synthetic descriptor application that records what it was asked to protect."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[Path, str]] = []
        self.fail = fail

    def __call__(self, path: Path, principal: str) -> None:
        self.calls.append((path, principal))
        if self.fail:
            raise writer.PrivateArtifactError(writer.PrivateArtifactDefect.SECURITY_APPLY_FAILED)


def _write(
    tmp_path: Path,
    *,
    payload: bytes = b"{}\n",
    name: str = "artifact.json",
    destination: str | None = None,
    security: rb.FileSecurity | None = None,
    security_of: Callable[[Path], rb.FileSecurity] | None = None,
    apply_security: Callable[[Path, str], None] | None = None,
) -> Path:
    root = _private_root(tmp_path)
    settled = security if security is not None else _security()
    inspect = security_of if security_of is not None else (lambda _path: settled)
    return writer.write_private_artifact(  # type: ignore[no-any-return]
        destination=destination if destination is not None else str(root / name),
        payload=payload,
        root_source=lambda: root,
        security_of=inspect,
        apply_security=apply_security if apply_security is not None else _Descriptor(),
    )


def test_the_writer_creates_one_owner_only_artifact(tmp_path: Path) -> None:
    descriptor = _Descriptor()
    payload = rb.canonical_binding_bytes(_environment_document())
    created = _write(tmp_path, payload=payload, apply_security=descriptor)
    assert created.read_bytes() == payload
    assert [principal for _path, principal in descriptor.calls] == [CURRENT]


def test_an_occupied_destination_is_a_refusal_and_not_an_overwrite(tmp_path: Path) -> None:
    """Collision fails closed. The artifact already there is left exactly as it was."""
    root = _private_root(tmp_path)
    occupied = root / "artifact.json"
    occupied.write_bytes(b"prior\n")
    with pytest.raises(writer.PrivateArtifactError) as caught:
        _write(tmp_path, payload=b"replacement\n")
    assert caught.value.defect is writer.PrivateArtifactDefect.DESTINATION_OCCUPIED
    assert occupied.read_bytes() == b"prior\n"


def test_the_create_is_one_exclusive_syscall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No check-then-write: the exclusive flag is what makes the collision atomic."""
    seen: list[int] = []
    original = os.open

    def _record(path: Any, flags: int, *rest: Any) -> int:
        seen.append(flags)
        return original(path, flags, *rest)

    monkeypatch.setattr(os, "open", _record)
    _write(tmp_path)
    assert len(seen) == 1
    assert seen[0] & os.O_EXCL
    assert seen[0] & os.O_CREAT


def test_a_failed_descriptor_leaves_nothing_behind(tmp_path: Path) -> None:
    root = _private_root(tmp_path)
    with pytest.raises(writer.PrivateArtifactError) as caught:
        _write(tmp_path, apply_security=_Descriptor(fail=True))
    assert caught.value.defect is writer.PrivateArtifactDefect.SECURITY_APPLY_FAILED
    assert not (root / "artifact.json").exists()


def test_a_result_that_does_not_satisfy_the_loader_policy_leaves_nothing_behind(
    tmp_path: Path,
) -> None:
    """The writer asks the loader's own question, and refuses its own output."""
    root = _private_root(tmp_path)
    with pytest.raises(writer.PrivateArtifactError) as caught:
        _write(tmp_path, security=_security(allow_principals=(CURRENT, EVERYONE)))
    assert caught.value.defect is writer.PrivateArtifactDefect.VERIFICATION_FAILED
    assert not (root / "artifact.json").exists()


def test_an_unanswerable_security_query_leaves_nothing_behind(tmp_path: Path) -> None:
    root = _private_root(tmp_path)

    def _unavailable(_path: Path) -> rb.FileSecurity:
        raise rb.RuntimeBindingError(rb.RuntimeBindingDefect.SECURITY_UNVERIFIABLE)

    with pytest.raises(writer.PrivateArtifactError) as caught:
        _write(tmp_path, security_of=_unavailable)
    assert caught.value.defect is writer.PrivateArtifactDefect.VERIFICATION_FAILED
    assert not (root / "artifact.json").exists()


def test_an_interrupted_write_is_not_retained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A half-written private artifact would be read next time as though it were meant."""
    root = _private_root(tmp_path)

    def _fails(*_args: object, **_kwargs: object) -> int:
        raise OSError("the device went away")

    monkeypatch.setattr(os, "fsync", _fails)
    with pytest.raises(writer.PrivateArtifactError) as caught:
        _write(tmp_path)
    assert caught.value.defect is writer.PrivateArtifactDefect.WRITE_FAILED
    assert not (root / "artifact.json").exists()


WRITER_REFUSALS: Final[tuple[tuple[str, dict[str, Any], Any], ...]] = (
    (
        "a payload that is not bytes",
        {"payload": "{}"},
        writer.PrivateArtifactDefect.PAYLOAD_MALFORMED,
    ),
    ("an empty payload", {"payload": b""}, writer.PrivateArtifactDefect.PAYLOAD_EMPTY),
    (
        "an oversized payload",
        {"payload": b"x" * (writer.MAX_PRIVATE_ARTIFACT_BYTES + 1)},
        writer.PrivateArtifactDefect.PAYLOAD_TOO_LARGE,
    ),
    (
        "a relative destination",
        {"destination": "artifact.json"},
        writer.PrivateArtifactDefect.PATH_REFUSED,
    ),
)


@pytest.mark.parametrize(
    ("overrides", "defect"),
    [(overrides, defect) for _label, overrides, defect in WRITER_REFUSALS],
    ids=[label for label, _overrides, _defect in WRITER_REFUSALS],
)
def test_the_writer_refuses_before_creating_anything(
    tmp_path: Path, overrides: dict[str, Any], defect: Any
) -> None:
    root = _private_root(tmp_path)
    with pytest.raises(writer.PrivateArtifactError) as caught:
        _write(tmp_path, **overrides)
    assert caught.value.defect is defect
    assert list(root.iterdir()) == []


def test_a_destination_outside_the_private_root_refuses(tmp_path: Path) -> None:
    with pytest.raises(writer.PrivateArtifactError) as caught:
        _write(tmp_path, destination=str(tmp_path / "elsewhere.json"))
    assert caught.value.defect is writer.PrivateArtifactDefect.PATH_REFUSED
    assert not (tmp_path / "elsewhere.json").exists()


def test_a_missing_parent_directory_refuses_rather_than_creating_one(tmp_path: Path) -> None:
    """The private root is the owner's to establish, with the descriptor they chose."""
    root = _private_root(tmp_path)
    with pytest.raises(writer.PrivateArtifactError) as caught:
        _write(tmp_path, destination=str(root / "nested" / "artifact.json"))
    assert caught.value.defect is writer.PrivateArtifactDefect.DIRECTORY_MISSING
    assert not (root / "nested").exists()


def test_the_real_descriptor_produces_a_result_the_loader_accepts(tmp_path: Path) -> None:
    """The ctypes path, exercised end to end on a genuine file.

    The policy above it is driven synthetically everywhere else; this is the one place
    the platform call itself runs, so ``SECURITY_APPLY_FAILED`` means "the platform
    refused" rather than "nobody ever asked it".
    """
    root = _private_root(tmp_path)
    payload = rb.canonical_binding_bytes(_environment_document())
    created = writer.write_private_artifact(
        destination=str(root / "real.json"), payload=payload, root_source=lambda: root
    )
    assert created.read_bytes() == payload

    security = rb.windows_file_security(created)
    rb.require_exclusive_security(security)
    assert security.inheritance_disabled is True
    assert security.allow_principals == (security.current_principal,)
    assert security.deny_principals == ()

    binding = rb.load_environment_binding(
        path=str(created), expected_account=ACCOUNT, root_source=lambda: root
    )
    assert binding.digest == rb.sha256_hex(payload)


def test_no_writer_refusal_carries_a_private_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(writer.PrivateArtifactError) as caught:
        _write(tmp_path, security=_security(owner=OTHER_USER))
    captured = capsys.readouterr()
    for surface in (str(caught.value), repr(caught.value), captured.out, captured.err):
        for canary in (CURRENT, OTHER_USER, BUCKET, ACCOUNT):
            assert canary not in surface


# ---------------------------------------------------------------------------
# The capture producer
# ---------------------------------------------------------------------------


class _Recorder:
    """A destination that records every payload it was handed, and creates nothing."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, bytes]] = []

    def __call__(self, *, destination: str, payload: bytes) -> Path:
        self.writes.append((destination, payload))
        return Path(destination)


class _FixedClock:
    def captured_at(self) -> str:
        return CAPTURED_AT


def _capture(
    *,
    recorder: _Recorder | None = None,
    authorization: object | None = None,
    modules: Mapping[str, object] | None = None,
    env: Mapping[str, str] | None = None,
    profile: str = "kalpamani-foundation",
    identity: str | None = None,
    destination: str = r"C:\synthetic\KalpaMani\private\environment.json",
    account: str | None = ACCOUNT,
    outputs: Mapping[str, Any] | None = None,
) -> tuple[Any, _Recorder]:
    sink = recorder if recorder is not None else _Recorder()
    outcome = capture.capture_environment_binding(
        authorization=(capture._CAPTURE_AUTHORIZATION if authorization is None else authorization),
        env={} if env is None else env,
        modules={} if modules is None else modules,
        governed_profile="kalpamani-foundation",
        profile_of=lambda: profile,
        identity_gate=lambda: identity,
        destination_source=lambda: destination,
        expected_account=lambda: account,
        governed_outputs=lambda: (
            {capture.LICENSED_BUCKET_OUTPUT: BUCKET} if outputs is None else outputs
        ),
        clock=_FixedClock(),
        write_artifact=sink,
    )
    return outcome, sink


def test_a_capture_writes_one_validated_environment_binding() -> None:
    outcome, sink = _capture()
    assert outcome is capture.CaptureOutcome.COMPLETED
    assert len(sink.writes) == 1

    _destination, payload = sink.writes[0]
    binding = rb.parse_environment_binding(
        json.loads(payload.decode("utf-8")),
        expected_account=ACCOUNT,
        digest=rb.sha256_hex(payload),
    )
    assert binding.licensed_bucket_name == BUCKET
    assert binding.target_account_id == ACCOUNT


def test_a_capture_binds_the_digest_to_the_outputs_it_consumed() -> None:
    _outcome, sink = _capture()
    document = json.loads(sink.writes[0][1].decode("utf-8"))
    expected = rb.sha256_hex(rb.canonical_binding_bytes({capture.LICENSED_BUCKET_OUTPUT: BUCKET}))
    assert document["provenance"]["outputs_digest"] == expected


def test_a_capture_reads_exactly_one_governed_output() -> None:
    """An output map carries role ARNs and a registry URL that each embed an account."""
    outputs = {
        capture.LICENSED_BUCKET_OUTPUT: BUCKET,
        "control_bucket_name": "synthetic-control-bucket-zz",
        "task_role_arn": "arn:aws:iam::" + OTHER_ACCOUNT + ":role/synthetic",
    }
    _outcome, sink = _capture(outputs=outputs)
    payload = sink.writes[0][1].decode("utf-8")
    assert BUCKET in payload
    assert "control_bucket_name" not in payload
    assert "arn:aws:iam" not in payload


CAPTURE_REFUSALS: Final[tuple[tuple[str, dict[str, Any], Any], ...]] = (
    (
        "no authorization",
        {"authorization": object()},
        capture.CaptureOutcome.REFUSED_NOT_AUTHORIZED,
    ),
    (
        "under a test runner",
        {"modules": {"pytest": object()}},
        capture.CaptureOutcome.REFUSED_EXECUTION_CONTEXT,
    ),
    (
        "in continuous integration",
        {"env": {"CI": "1"}},
        capture.CaptureOutcome.REFUSED_EXECUTION_CONTEXT,
    ),
    (
        "under the acquisition actor",
        {"profile": "kalpamani-qualification-acquisition"},
        capture.CaptureOutcome.REFUSED_PROFILE,
    ),
    (
        "under the assessment actor",
        {"profile": "kalpamani-qualification-assessment"},
        capture.CaptureOutcome.REFUSED_PROFILE,
    ),
    ("with no profile pinned", {"profile": ""}, capture.CaptureOutcome.REFUSED_PROFILE),
    (
        "with a failing identity gate",
        {"identity": "the identity did not resolve"},
        capture.CaptureOutcome.REFUSED_IDENTITY,
    ),
    ("with no destination", {"destination": "  "}, capture.CaptureOutcome.REFUSED_DESTINATION),
    (
        "with no governed account binding",
        {"account": None},
        capture.CaptureOutcome.REFUSED_EXPECTED_ACCOUNT,
    ),
    ("with no licensed bucket output", {"outputs": {}}, capture.CaptureOutcome.REFUSED_OUTPUTS),
    (
        "with a bucket output of the wrong type",
        {"outputs": {"licensed_bucket_name": None}},
        capture.CaptureOutcome.REFUSED_OUTPUTS,
    ),
    (
        "with a bucket output the contract refuses",
        {"outputs": {"licensed_bucket_name": "s3://" + BUCKET}},
        capture.CaptureOutcome.REFUSED_DOCUMENT,
    ),
    (
        "with an account the contract refuses",
        {"account": "1234"},
        capture.CaptureOutcome.REFUSED_DOCUMENT,
    ),
)


@pytest.mark.parametrize(
    ("overrides", "outcome"),
    [(overrides, outcome) for _label, overrides, outcome in CAPTURE_REFUSALS],
    ids=[label for label, _overrides, _outcome in CAPTURE_REFUSALS],
)
def test_a_capture_refuses_and_writes_nothing(overrides: dict[str, Any], outcome: Any) -> None:
    sink = _Recorder()
    with pytest.raises(capture.CaptureError) as caught:
        _capture(recorder=sink, **overrides)
    assert caught.value.outcome is outcome
    assert sink.writes == []


def test_a_capture_refuses_the_actor_before_it_reads_anything() -> None:
    """Order is the property: a wrong actor never reaches an output or a destination."""
    reached: list[str] = []

    def _outputs() -> Mapping[str, Any]:
        reached.append("outputs")
        return {}

    def _destination() -> str:
        reached.append("destination")
        return ""

    with pytest.raises(capture.CaptureError):
        capture.capture_environment_binding(
            authorization=capture._CAPTURE_AUTHORIZATION,
            env={},
            modules={},
            governed_profile="kalpamani-foundation",
            profile_of=lambda: "kalpamani-qualification-acquisition",
            identity_gate=lambda: None,
            destination_source=_destination,
            expected_account=lambda: ACCOUNT,
            governed_outputs=_outputs,
            clock=_FixedClock(),
            write_artifact=_Recorder(),
        )
    assert reached == []


# ---------------------------------------------------------------------------
# The materialization gate
# ---------------------------------------------------------------------------


class _Verifier:
    """A synthetic re-read that answers with whatever bucket a test asks it to."""

    def __init__(self, bucket: str | None = BUCKET, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.bucket = bucket
        self.fail = fail

    def __call__(self, *, destination: str, expected_account: str | None) -> Any:
        self.calls.append((destination, expected_account))
        if self.fail:
            raise rb.RuntimeBindingError(rb.RuntimeBindingDefect.FILE_UNREADABLE)
        return rb.QualificationRuntimeBinding(
            licensed_bucket_name=self.bucket if self.bucket is not None else OTHER_BUCKET,
            partition=rb.EXPECTED_PARTITION,
            region=rb.EXPECTED_REGION,
            acquisition_profile=rb.EXPECTED_ACQUISITION_PROFILE,
        )


def _environment_binding(**overrides: Any) -> rb.QualificationEnvironmentBinding:
    settled: dict[str, Any] = {
        "target_account_id": ACCOUNT,
        "licensed_bucket_name": BUCKET,
        "partition": rb.EXPECTED_PARTITION,
        "region": rb.EXPECTED_REGION,
        "digest": OUTPUTS_DIGEST,
    }
    settled.update(overrides)
    return rb.QualificationEnvironmentBinding(**settled)


def _materialize(
    *,
    recorder: _Recorder | None = None,
    verifier: _Verifier | None = None,
    authorization: object | None = None,
    modules: Mapping[str, object] | None = None,
    env: Mapping[str, str] | None = None,
    source: str = r"C:\synthetic\KalpaMani\private\environment.json",
    destination: str = r"C:\synthetic\KalpaMani\private\runtime.json",
    account: str | None = ACCOUNT,
    loader: Callable[..., Any] | None = None,
    module: Any = None,
) -> tuple[Any, _Recorder, _Verifier]:
    target = materialize if module is None else module
    sink = recorder if recorder is not None else _Recorder()
    checker = verifier if verifier is not None else _Verifier()
    outcome = target.materialize_runtime_binding(
        authorization=(
            target._MATERIALIZATION_AUTHORIZATION if authorization is None else authorization
        ),
        env={} if env is None else env,
        modules={} if modules is None else modules,
        source_path=lambda: source,
        destination_source=lambda: destination,
        expected_account=lambda: account,
        load_environment_binding=(
            loader if loader is not None else (lambda **_kwargs: _environment_binding())
        ),
        write_artifact=sink,
        verify_runtime_binding=checker,
    )
    return outcome, sink, checker


def test_a_materialization_writes_one_verified_runtime_binding() -> None:
    outcome, sink, checker = _materialize()
    assert outcome is materialize.MaterializationOutcome.COMPLETED
    assert len(sink.writes) == 1
    assert len(checker.calls) == 1

    document = json.loads(sink.writes[0][1].decode("utf-8"))
    binding = rb.parse_runtime_binding(document, expected_account=ACCOUNT)
    assert binding.licensed_bucket_name == BUCKET
    assert document["acquisition_profile"] == rb.EXPECTED_ACQUISITION_PROFILE


def test_the_runtime_binding_carries_the_digest_of_the_source_bytes(tmp_path: Path) -> None:
    """The correction, end to end: a real file in, its digest in the written field.

    The environment binding here is a real synthetic file read by the production
    loader, so the digest under test is the one that loader computed over the bytes on
    disk -- not a value this test handed in.
    """
    root = _private_root(tmp_path)
    source = root / "environment.json"
    payload = rb.canonical_binding_bytes(_environment_document())
    source.write_bytes(payload)

    def _loader(*, path: str, expected_account: str | None) -> Any:
        return rb.load_environment_binding(
            path=path,
            expected_account=expected_account,
            root_source=lambda: root,
            security_of=lambda _path: _security(),
        )

    _outcome, sink, _checker = _materialize(source=str(source), loader=_loader)
    document = json.loads(sink.writes[0][1].decode("utf-8"))
    assert document["provenance"]["environment_binding_sha256"] == rb.sha256_hex(payload)


def test_the_written_provenance_names_the_accepted_implementation() -> None:
    _outcome, sink, _checker = _materialize()
    provenance = json.loads(sink.writes[0][1].decode("utf-8"))["provenance"]
    assert provenance["implementation_commit"] == materialize.IMPLEMENTATION_COMMIT
    assert provenance["implementation_tree"] == materialize.IMPLEMENTATION_TREE


MATERIALIZATION_REFUSALS: Final[tuple[tuple[str, dict[str, Any], Any], ...]] = (
    (
        "no authorization",
        {"authorization": object()},
        materialize.MaterializationOutcome.REFUSED_NOT_AUTHORIZED,
    ),
    (
        "under a test runner",
        {"modules": {"pytest": object()}},
        materialize.MaterializationOutcome.REFUSED_EXECUTION_CONTEXT,
    ),
    (
        "in continuous integration",
        {"env": {"GITHUB_ACTIONS": "true"}},
        materialize.MaterializationOutcome.REFUSED_EXECUTION_CONTEXT,
    ),
    (
        "with no source path",
        {"source": "  "},
        materialize.MaterializationOutcome.REFUSED_SOURCE_PATH,
    ),
    (
        "with no governed account binding",
        {"account": None},
        materialize.MaterializationOutcome.REFUSED_EXPECTED_ACCOUNT,
    ),
    (
        "with no destination",
        {"destination": ""},
        materialize.MaterializationOutcome.REFUSED_DESTINATION,
    ),
)


@pytest.mark.parametrize(
    ("overrides", "outcome"),
    [(overrides, outcome) for _label, overrides, outcome in MATERIALIZATION_REFUSALS],
    ids=[label for label, _overrides, _outcome in MATERIALIZATION_REFUSALS],
)
def test_a_materialization_refuses_and_writes_nothing(
    overrides: dict[str, Any], outcome: Any
) -> None:
    sink = _Recorder()
    with pytest.raises(materialize.MaterializationError) as caught:
        _materialize(recorder=sink, **overrides)
    assert caught.value.outcome is outcome
    assert sink.writes == []


ENVIRONMENT_REFUSALS: Final[tuple[tuple[str, dict[str, Any]], ...]] = (
    ("an account that is not the governed one", {"target_account_id": OTHER_ACCOUNT}),
    ("another region", {"region": "eu-west-1"}),
    ("another partition", {"partition": "aws-us-gov"}),
)


@pytest.mark.parametrize(
    "overrides",
    [overrides for _label, overrides in ENVIRONMENT_REFUSALS],
    ids=[label for label, _overrides in ENVIRONMENT_REFUSALS],
)
def test_an_inconsistent_environment_binding_refuses(overrides: dict[str, Any]) -> None:
    sink = _Recorder()
    with pytest.raises(materialize.MaterializationError) as caught:
        _materialize(recorder=sink, loader=lambda **_kwargs: _environment_binding(**overrides))
    assert caught.value.outcome is materialize.MaterializationOutcome.REFUSED_ENVIRONMENT_BINDING
    assert sink.writes == []


def test_a_refused_environment_binding_stops_the_gate() -> None:
    def _refusing(**_kwargs: Any) -> Any:
        raise rb.RuntimeBindingError(rb.RuntimeBindingDefect.ACL_NOT_EXCLUSIVE)

    sink = _Recorder()
    with pytest.raises(materialize.MaterializationError) as caught:
        _materialize(recorder=sink, loader=_refusing)
    assert caught.value.outcome is materialize.MaterializationOutcome.REFUSED_ENVIRONMENT_BINDING
    assert sink.writes == []


def test_a_loader_answering_with_the_wrong_type_refuses() -> None:
    sink = _Recorder()
    with pytest.raises(materialize.MaterializationError) as caught:
        _materialize(recorder=sink, loader=lambda **_kwargs: object())
    assert caught.value.outcome is materialize.MaterializationOutcome.REFUSED_ENVIRONMENT_BINDING
    assert sink.writes == []


def test_a_written_artifact_that_will_not_load_is_reported() -> None:
    with pytest.raises(materialize.MaterializationError) as caught:
        _materialize(verifier=_Verifier(fail=True))
    assert caught.value.outcome is materialize.MaterializationOutcome.REFUSED_VERIFICATION


def test_a_written_artifact_naming_another_bucket_is_reported() -> None:
    with pytest.raises(materialize.MaterializationError) as caught:
        _materialize(verifier=_Verifier(bucket=OTHER_BUCKET))
    assert caught.value.outcome is materialize.MaterializationOutcome.REFUSED_VERIFICATION


def test_the_gate_makes_no_aws_call_and_starts_no_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Traps rather than a count after the fact: a call that happened has happened."""

    def _trap(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("the materialization gate reached a process or a socket")

    monkeypatch.setattr(subprocess, "run", _trap)
    monkeypatch.setattr(subprocess, "Popen", _trap)
    monkeypatch.setattr(socket, "socket", _trap)
    outcome, _sink, _checker = _materialize()
    assert outcome is materialize.MaterializationOutcome.COMPLETED


# ---------------------------------------------------------------------------
# Isolation -- who may reach the capture, and what the capture may reach
# ---------------------------------------------------------------------------


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                found.add(node.module)
            found.update(alias.name for alias in node.names)
    return found


def test_the_acquisition_entry_point_names_neither_operator_tool() -> None:
    """Necessary and not sufficient -- the call-graph guard is the semantic one."""
    acquire = ACQUIRE_PATH.read_text(encoding="utf-8")
    for tool in (
        "qualification_environment_binding_capture",
        "qualification_runtime_binding_materialize",
        "qualification_private_artifacts",
        "load_environment_binding",
    ):
        assert tool not in acquire, tool


def test_the_materialization_gate_names_no_terraform_reach() -> None:
    """It reads a private file and the local account binding, and nothing else."""
    imported = _imported_names(MATERIALIZE_PATH)
    assert "tf_outputs" not in imported
    assert "expected_account" in imported
    source = MATERIALIZE_PATH.read_text(encoding="utf-8")
    for forbidden in ("tf_outputs", "backend_settings", "-chdir=", "subprocess", "boto3"):
        assert forbidden not in source, forbidden


def test_the_capture_is_the_only_tool_that_reaches_the_governed_outputs() -> None:
    assert "tf_outputs" in _imported_names(CAPTURE_PATH)
    for other in (MATERIALIZE_PATH, WRITER_PATH, ACQUIRE_PATH):
        assert "tf_outputs" not in other.read_text(encoding="utf-8"), other.name


def test_the_writer_reads_no_environment_and_starts_no_process() -> None:
    source = WRITER_PATH.read_text(encoding="utf-8")
    for forbidden in ("os.environ", "subprocess", "boto3", "tf_outputs"):
        assert forbidden not in source, forbidden


def test_the_environment_variable_name_is_spelled_once() -> None:
    """Three files use it; one declares it, and the rest import that declaration."""
    declarations = [
        path
        for path in (WRITER_PATH, CAPTURE_PATH, MATERIALIZE_PATH)
        if f'= "{rb.ENVIRONMENT_BINDING_ENV_VAR}"' in path.read_text(encoding="utf-8")
    ]
    assert declarations == []
    module = (
        PROJECT_ROOT / "src" / "kalpamani" / "data" / "qualify" / "sharadar" / "runtime_binding.py"
    )
    assert (
        f'ENVIRONMENT_BINDING_ENV_VAR: Final = "{rb.ENVIRONMENT_BINDING_ENV_VAR}"'
        in module.read_text(encoding="utf-8")
    )


def test_the_contract_module_reads_no_environment_variable_for_the_source() -> None:
    """Run A must not be able to read the environment binding, even by accident.

    The name is declared in the contract module because one spelling is better than
    three, and it is deliberately never looked up there: the loader takes its path as
    an argument, so only a caller that chose to supply one can reach the artifact.
    """
    module = (
        PROJECT_ROOT / "src" / "kalpamani" / "data" / "qualify" / "sharadar" / "runtime_binding.py"
    )
    tree = ast.parse(module.read_text(encoding="utf-8"))
    keys: set[str] = set()
    for call in ast.walk(tree):
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "get"
            and isinstance(call.func.value, ast.Attribute)
            and call.func.value.attr == "environ"
            and call.args
        ):
            key = call.args[0]
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                keys.add(key.value)
            elif isinstance(key, ast.Name):
                keys.add(key.id)
    assert rb.ENVIRONMENT_BINDING_ENV_VAR not in keys
    assert "ENVIRONMENT_BINDING_ENV_VAR" not in keys


# ---------------------------------------------------------------------------
# Mutations -- each guard, watched failing
# ---------------------------------------------------------------------------


def _mutated_source(path: Path, replacements: tuple[tuple[str, str], ...]) -> str:
    """One module's source with each named property removed exactly once."""
    source = path.read_text(encoding="utf-8")
    for original, replacement in replacements:
        assert source.count(original) == 1, original
        source = source.replace(original, replacement)
    return source


def _mutant(name: str, path: Path, replacements: tuple[tuple[str, str], ...]) -> ModuleType:
    """One operator module with properties removed, **in memory only**."""
    module = ModuleType(name)
    module.__file__ = str(path)
    exec(compile(_mutated_source(path, replacements), str(path), "exec"), module.__dict__)  # noqa: S102
    return module


#: The exact source lines each mutation removes. Every one is a property some check
#: above depends on, so removing it must make that check fail rather than pass quietly.
DIGEST_BINDING: Final = '"environment_binding_sha256": environment.digest,'
COMPOSED_VALIDATION: Final = "        parse_runtime_binding(document, expected_account=account)\n"
#: Split across three literals only because the line it names is longer than this
#: file may be. They are joined before anything is matched.
ACCOUNT_CHECK: Final = (
    "    if environment.target_account_id != account:\n"
    "        raise MaterializationError("
    "MaterializationOutcome.REFUSED_ENVIRONMENT_BINDING) from None\n"
)
ACL_VERIFICATION: Final = "        require_exclusive_security(after)\n"


def test_every_mutation_target_appears_exactly_once_in_the_real_source() -> None:
    """A mutation that matched nothing would prove nothing, silently."""
    materialize_source = MATERIALIZE_PATH.read_text(encoding="utf-8")
    writer_source = WRITER_PATH.read_text(encoding="utf-8")
    assert materialize_source.count(DIGEST_BINDING) == 1
    assert materialize_source.count(COMPOSED_VALIDATION) == 1
    assert materialize_source.count(ACCOUNT_CHECK) == 1
    assert writer_source.count(ACL_VERIFICATION) == 1


def test_the_mutation_helper_actually_removes_the_property() -> None:
    mutated = _mutated_source(MATERIALIZE_PATH, ((DIGEST_BINDING, ""),))
    assert DIGEST_BINDING in MATERIALIZE_PATH.read_text(encoding="utf-8")
    assert DIGEST_BINDING not in mutated


def test_removing_the_digest_binding_is_caught() -> None:
    """A materialization that stops carrying the source digest stops being provenance."""
    _outcome, real_sink, _checker = _materialize()
    real = json.loads(real_sink.writes[0][1].decode("utf-8"))
    assert real["provenance"]["environment_binding_sha256"] == OUTPUTS_DIGEST

    mutant = _mutant(
        "_digest_mutant",
        MATERIALIZE_PATH,
        ((DIGEST_BINDING, '"environment_binding_sha256": "' + COMMIT + COMMIT[:24] + '",'),),
    )
    _mutated_outcome, mutated_sink, _mutated_checker = _materialize(module=mutant)
    mutated = json.loads(mutated_sink.writes[0][1].decode("utf-8"))
    assert mutated["provenance"]["environment_binding_sha256"] != OUTPUTS_DIGEST


def test_removing_only_one_half_of_the_account_consistency_still_refuses() -> None:
    """Two independent checks stand between a foreign binding and an artifact."""

    def foreign(**_kwargs: Any) -> rb.QualificationEnvironmentBinding:
        return _environment_binding(target_account_id=OTHER_ACCOUNT)

    sink = _Recorder()
    with pytest.raises(materialize.MaterializationError) as caught:
        _materialize(recorder=sink, loader=foreign)
    assert caught.value.outcome is materialize.MaterializationOutcome.REFUSED_ENVIRONMENT_BINDING
    assert sink.writes == []

    without_explicit = _mutant("_account_mutant_explicit", MATERIALIZE_PATH, ((ACCOUNT_CHECK, ""),))
    with pytest.raises(without_explicit.MaterializationError) as still:
        _materialize(module=without_explicit, loader=foreign)
    assert still.value.outcome is without_explicit.MaterializationOutcome.REFUSED_DOCUMENT

    without_validation = _mutant(
        "_account_mutant_validation", MATERIALIZE_PATH, ((COMPOSED_VALIDATION, "        pass\n"),)
    )
    with pytest.raises(without_validation.MaterializationError):
        _materialize(module=without_validation, loader=foreign)


def test_removing_the_whole_account_consistency_is_caught() -> None:
    """With both halves gone, a binding for another deployment reaches the artifact."""
    mutant = _mutant(
        "_account_mutant_both",
        MATERIALIZE_PATH,
        ((ACCOUNT_CHECK, ""), (COMPOSED_VALIDATION, "        pass\n")),
    )
    _outcome, sink, _checker = _materialize(
        module=mutant,
        loader=lambda **_kwargs: _environment_binding(target_account_id=OTHER_ACCOUNT),
    )
    written = json.loads(sink.writes[0][1].decode("utf-8"))
    assert written["target_account_id"] == OTHER_ACCOUNT


def test_removing_the_access_control_verification_is_caught(tmp_path: Path) -> None:
    """Without it the writer keeps a file every reader is required to refuse."""
    root = _private_root(tmp_path)
    unsafe = _security(allow_principals=(CURRENT, EVERYONE))

    with pytest.raises(writer.PrivateArtifactError) as caught:
        _write(tmp_path, security=unsafe)
    assert caught.value.defect is writer.PrivateArtifactDefect.VERIFICATION_FAILED
    assert not (root / "artifact.json").exists()

    mutant = _mutant("_acl_mutant", WRITER_PATH, ((ACL_VERIFICATION, "        pass\n"),))
    created = mutant.write_private_artifact(
        destination=str(root / "artifact.json"),
        payload=b"{}\n",
        root_source=lambda: root,
        security_of=lambda _path: unsafe,
        apply_security=_Descriptor(),
    )
    assert Path(str(created)).exists()
    with pytest.raises(rb.RuntimeBindingError) as refused:
        rb.require_exclusive_security(unsafe)
    assert refused.value.defect is rb.RuntimeBindingDefect.ACL_NOT_EXCLUSIVE


def test_no_mutation_reaches_the_repository_source() -> None:
    """Every mutation above is a string in memory. The tracked files are untouched."""
    assert DIGEST_BINDING in MATERIALIZE_PATH.read_text(encoding="utf-8")
    assert COMPOSED_VALIDATION in MATERIALIZE_PATH.read_text(encoding="utf-8")
    assert ACCOUNT_CHECK in MATERIALIZE_PATH.read_text(encoding="utf-8")
    assert ACL_VERIFICATION in WRITER_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Nothing private reaches Git, and no rule is restated here
# ---------------------------------------------------------------------------

NEW_SURFACES: Final[tuple[Path, ...]] = (WRITER_PATH, CAPTURE_PATH, MATERIALIZE_PATH)


@pytest.mark.parametrize("path", NEW_SURFACES, ids=lambda path: path.name)
def test_no_new_surface_carries_a_private_identifier(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for marker in ("AKIA", "amazonaws.com", "awsapps.com", "sap4n", "s3://"):
        assert marker not in text, marker
    assert re.search(r"\b\d{12}\b", text) is None


def test_this_suite_restates_no_production_grammar() -> None:
    """A test that reimplements a rule tests its own copy of it.

    Every field rule here is asked of the production validator, so a compiled pattern
    of this file's own would be a second grammar nobody reconciled with the first.
    """
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    compiled = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "compile"
    ]
    assert compiled == []
