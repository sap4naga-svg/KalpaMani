"""The private assessment runtime binding and its materialization gate (ADR-0025).

ADR-0023 gave the acquisition actor an ACL-protected private file in place of a
Terraform state read, and said in its own text that the combined assessment was out of
scope. This is that actor's contract, and it had **two** prohibited dependencies to
lose rather than one: the state read, and the local Terraform variables file its
account binding came from.

What is checked here:

**The contract.** A synthetic assessment binding is driven through the production
validator -- every trust-boundary clause, every field rule, and the two-way refusal
that keeps this artifact and the acquisition one from validating as each other -- with
an injected security inspector and a synthetic private root. **Nothing here
reimplements a production rule**: the tests build documents and ask the real validator,
and a scan below refuses a grammar of this file's own.

**The gate.** The operator command is driven with injected dependencies that count what
they were asked for, so "no AWS call", "no Terraform" and "one atomic create" are
observations rather than claims.

**The mutations.** Five properties are removed in memory -- the account comparison, the
actor separation, the ACL verification, the source digest and the post-write
verification -- and each guard is watched failing. A guard nobody has watched fail is a
guard nobody has tested. **No production file is rewritten by any of it.**

**Every identifier is invented.** No real account, bucket, path, principal or deployment
value appears, and no real private artifact is created or read.
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
CONTRACT_PATH: Final = (
    PROJECT_ROOT / "src" / "kalpamani" / "data" / "qualify" / "sharadar" / "runtime_binding.py"
)
GATE_PATH: Final = SCRIPTS / "qualification_assessment_binding_materialize.py"
ACQUIRE_GATE_PATH: Final = SCRIPTS / "qualification_runtime_binding_materialize.py"
ASSESS_PATH: Final = SCRIPTS / "sharadar_qualification_assessment.py"
ACQUIRE_PATH: Final = SCRIPTS / "sharadar_empirical_qualification.py"
WRITER_PATH: Final = SCRIPTS / "qualification_private_artifacts.py"

#: Synthetic, and matching no deployment. A twelve-digit run of zeroes is not an
#: account anybody holds, and the bucket names itself.
ACCOUNT: Final = "000000000000"
OTHER_ACCOUNT: Final = "999999999999"
BUCKET: Final = "synthetic-licensed-bucket-zz"
OTHER_BUCKET: Final = "synthetic-licensed-bucket-yy"
#: Deliberately a different length from ``BUCKET``, so a document swapped for this one
#: changes the size in the file identity rather than only its modification time.
SWAPPED_BUCKET: Final = "synthetic-licensed-bucket-swapped"
CURRENT: Final = "S-1-5-21-0-0-0-1001"
OTHER_USER: Final = "S-1-5-21-0-0-0-1002"
EVERYONE: Final = "S-1-1-0"
COMMIT: Final = "0123456789abcdef0123456789abcdef01234567"
TREE: Final = "89abcdef0123456789abcdef0123456789abcdef"
ENVELOPE: Final = "0123456789abcdef" * 4
CAPTURED_AT: Final = "2000-01-01T00:00:00Z"


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


gate = _load_script("_assessment_binding_gate_under_test", GATE_PATH)


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------


def _document(**overrides: Any) -> dict[str, Any]:
    """A well-formed synthetic assessment binding, built from production constants."""
    document: dict[str, Any] = {
        "schema_version": rb.ASSESSMENT_RUNTIME_BINDING_SCHEMA_VERSION,
        "binding_kind": rb.ASSESSMENT_RUNTIME_BINDING_KIND,
        "contract_id": rb.ASSESSMENT_RUNTIME_BINDING_CONTRACT_ID,
        "aws_partition": rb.EXPECTED_PARTITION,
        "aws_region": rb.EXPECTED_REGION,
        "target_account_id": ACCOUNT,
        "assessment_profile": rb.EXPECTED_ASSESSMENT_PROFILE,
        "licensed_bucket_name": BUCKET,
        "provenance": {
            "implementation_commit": COMMIT,
            "implementation_tree": TREE,
            "environment_binding_sha256": ENVELOPE,
        },
    }
    document.update(overrides)
    return document


def _acquisition_document(**overrides: Any) -> dict[str, Any]:
    """A well-formed synthetic ACQUISITION binding, for the two-way refusal."""
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


def _load(
    tmp_path: Path,
    *,
    raw: bytes | None = None,
    security: rb.FileSecurity | None = None,
    security_of: Callable[[Path], rb.FileSecurity] | None = None,
    path_override: str | None = None,
    root_override: Path | None = None,
) -> rb.QualificationAssessmentRuntimeBinding:
    """Drive the production loader against a synthetic private root."""
    root = _private_root(tmp_path)
    target = root / "assessment.json"
    if raw is None:
        raw = rb.canonical_binding_bytes(_document())
    target.write_bytes(raw)

    settled = security if security is not None else _security()
    inspect = security_of if security_of is not None else (lambda _path: settled)
    return rb.load_assessment_runtime_binding(
        path_source=lambda: path_override if path_override is not None else str(target),
        root_source=lambda: root_override if root_override is not None else root,
        security_of=inspect,
    )


def _refused(tmp_path: Path, **kwargs: Any) -> pytest.ExceptionInfo[rb.RuntimeBindingError]:
    with pytest.raises(rb.RuntimeBindingError) as caught:
        _load(tmp_path, **kwargs)
    return caught


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------


def test_a_valid_synthetic_assessment_binding_is_accepted(tmp_path: Path) -> None:
    binding = _load(tmp_path)
    assert binding.licensed_bucket_name == BUCKET
    assert binding.target_account_id == ACCOUNT
    assert binding.partition == rb.EXPECTED_PARTITION
    assert binding.region == rb.EXPECTED_REGION
    assert binding.assessment_profile == rb.EXPECTED_ASSESSMENT_PROFILE


def test_the_result_repr_carries_neither_the_account_nor_the_bucket(tmp_path: Path) -> None:
    rendered = repr(_load(tmp_path))
    assert ACCOUNT not in rendered
    assert BUCKET not in rendered
    assert rb.EXPECTED_ASSESSMENT_PROFILE in rendered


def test_the_result_is_immutable_and_refuses_subclassing(tmp_path: Path) -> None:
    binding = _load(tmp_path)
    with pytest.raises(AttributeError):
        binding.licensed_bucket_name = OTHER_BUCKET  # type: ignore[misc]
    with pytest.raises(TypeError):

        class _Wider(rb.QualificationAssessmentRuntimeBinding):  # pragma: no cover - refused
            pass


def test_the_binding_carries_the_account_the_acquisition_one_drops(tmp_path: Path) -> None:
    """The one substantive difference, and the reason it exists.

    The acquisition binding validates the account against a governed local Terraform
    input and then discards it. The assessment path may not read that input at all, so
    this artifact *is* the account binding -- and a value the caller never receives is
    a value the caller cannot compare an authenticated identity against.
    """
    assert _load(tmp_path).target_account_id == ACCOUNT
    assert not hasattr(
        rb.QualificationRuntimeBinding(
            licensed_bucket_name=BUCKET,
            partition=rb.EXPECTED_PARTITION,
            region=rb.EXPECTED_REGION,
            acquisition_profile=rb.EXPECTED_ACQUISITION_PROFILE,
        ),
        "target_account_id",
    )


def test_the_parser_takes_no_expected_account_argument() -> None:
    """Read out of the signature: the binding is the account source, not a claimant."""
    import inspect as introspection

    parameters = introspection.signature(rb.parse_assessment_runtime_binding).parameters
    assert "expected_account" not in parameters
    assert "expected_account" in introspection.signature(rb.parse_runtime_binding).parameters


# -- the two artifacts cannot be confused --------------------------------------


def test_an_acquisition_binding_is_refused_by_the_assessment_loader(tmp_path: Path) -> None:
    caught = _refused(tmp_path, raw=rb.canonical_binding_bytes(_acquisition_document()))
    assert caught.value.defect is rb.RuntimeBindingDefect.FIELD_UNKNOWN


def test_an_assessment_binding_is_refused_by_the_acquisition_loader() -> None:
    with pytest.raises(rb.RuntimeBindingError) as caught:
        rb.parse_runtime_binding(_document(), expected_account=ACCOUNT)
    assert caught.value.defect is rb.RuntimeBindingDefect.FIELD_UNKNOWN


def test_an_environment_binding_is_refused_by_the_assessment_loader() -> None:
    environment = {
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
            "outputs_digest": ENVELOPE,
        },
    }
    with pytest.raises(rb.RuntimeBindingError) as caught:
        rb.parse_assessment_runtime_binding(environment)
    assert caught.value.defect is rb.RuntimeBindingDefect.FIELD_MISSING


def test_the_three_kinds_and_contracts_are_all_distinct() -> None:
    kinds: set[str] = {
        rb.RUNTIME_BINDING_KIND,
        rb.ASSESSMENT_RUNTIME_BINDING_KIND,
        rb.ENVIRONMENT_BINDING_KIND,
    }
    contracts: set[str] = {
        rb.RUNTIME_BINDING_CONTRACT_ID,
        rb.ASSESSMENT_RUNTIME_BINDING_CONTRACT_ID,
        rb.ENVIRONMENT_BINDING_CONTRACT_ID,
    }
    variables: set[str] = {
        rb.RUNTIME_BINDING_ENV_VAR,
        rb.ASSESSMENT_RUNTIME_BINDING_ENV_VAR,
        rb.ENVIRONMENT_BINDING_ENV_VAR,
    }
    assert len(kinds) == 3
    assert len(contracts) == 3
    assert len(variables) == 3


# -- path selection and containment -------------------------------------------


def test_the_production_path_source_reads_the_one_fixed_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(rb.ASSESSMENT_RUNTIME_BINDING_ENV_VAR, r"C:\synthetic\assessment.json")
    assert rb.assessment_runtime_binding_path() == r"C:\synthetic\assessment.json"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_the_production_path_source_refuses_a_missing_or_blank_variable(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv(rb.ASSESSMENT_RUNTIME_BINDING_ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(rb.ASSESSMENT_RUNTIME_BINDING_ENV_VAR, value)
    with pytest.raises(rb.RuntimeBindingError) as caught:
        rb.assessment_runtime_binding_path()
    assert caught.value.defect is rb.RuntimeBindingDefect.ENVIRONMENT_UNSET


def test_the_production_path_source_does_not_read_the_acquisition_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Setting the other actor's variable selects nothing here."""
    monkeypatch.delenv(rb.ASSESSMENT_RUNTIME_BINDING_ENV_VAR, raising=False)
    monkeypatch.setenv(rb.RUNTIME_BINDING_ENV_VAR, r"C:\synthetic\acquisition.json")
    with pytest.raises(rb.RuntimeBindingError) as caught:
        rb.assessment_runtime_binding_path()
    assert caught.value.defect is rb.RuntimeBindingDefect.ENVIRONMENT_UNSET


def test_a_relative_path_refuses(tmp_path: Path) -> None:
    caught = _refused(tmp_path, path_override="assessment.json")
    assert caught.value.defect is rb.RuntimeBindingDefect.PATH_NOT_ABSOLUTE


def test_a_blank_selected_path_refuses(tmp_path: Path) -> None:
    caught = _refused(tmp_path, path_override="   ")
    assert caught.value.defect is rb.RuntimeBindingDefect.ENVIRONMENT_UNSET


def test_a_path_outside_the_private_root_refuses(tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere.json"
    outside.write_bytes(rb.canonical_binding_bytes(_document()))
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


def test_a_missing_file_refuses_before_anything_is_opened(tmp_path: Path) -> None:
    root = _private_root(tmp_path)
    opened: list[str] = []

    def _watching(path: Path) -> rb.FileSecurity:
        opened.append(str(path))
        return _security()

    caught = _refused(
        tmp_path,
        path_override=str(root / "absent.json"),
        security_of=_watching,
    )
    assert caught.value.defect is rb.RuntimeBindingDefect.PATH_NOT_A_REGULAR_FILE
    assert opened == []


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


def test_a_reparse_point_in_the_chain_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A junction anywhere from the boundary down makes containment cosmetic."""
    root = _private_root(tmp_path)
    target = root / "assessment.json"
    target.write_bytes(rb.canonical_binding_bytes(_document()))
    real_lstat = Path.lstat

    def _lstat(self: Path) -> Any:
        entry = real_lstat(self)
        if self == target:
            return _stat_with(entry, attributes=0x400)
        return entry

    monkeypatch.setattr(Path, "lstat", _lstat)
    caught = _refused(tmp_path, path_override=str(target))
    assert caught.value.defect is rb.RuntimeBindingDefect.PATH_IS_A_LINK


# -- ownership and the discretionary access-control list -----------------------

ACL_REFUSALS: Final[tuple[tuple[str, dict[str, Any], rb.RuntimeBindingDefect], ...]] = (
    (
        "another owner",
        {"owner": OTHER_USER},
        rb.RuntimeBindingDefect.OWNER_NOT_CURRENT_USER,
    ),
    (
        "inheritance enabled",
        {"inheritance_disabled": False},
        rb.RuntimeBindingDefect.ACL_INHERITANCE_ENABLED,
    ),
    (
        "an extra principal",
        {"allow_principals": (CURRENT, EVERYONE)},
        rb.RuntimeBindingDefect.ACL_NOT_EXCLUSIVE,
    ),
    (
        "somebody else's allow entry",
        {"allow_principals": (OTHER_USER,)},
        rb.RuntimeBindingDefect.ACL_NOT_EXCLUSIVE,
    ),
    (
        "no allow entry at all",
        {"allow_principals": ()},
        rb.RuntimeBindingDefect.ACL_NOT_EXCLUSIVE,
    ),
    (
        "a deny entry",
        {"deny_principals": (OTHER_USER,)},
        rb.RuntimeBindingDefect.ACL_DENY_PRESENT,
    ),
)


@pytest.mark.parametrize(
    ("overrides", "defect"),
    [(overrides, defect) for _label, overrides, defect in ACL_REFUSALS],
    ids=[label for label, _overrides, _defect in ACL_REFUSALS],
)
def test_an_unsafe_access_control_list_refuses(
    tmp_path: Path, overrides: dict[str, Any], defect: rb.RuntimeBindingDefect
) -> None:
    caught = _refused(tmp_path, security=_security(**overrides))
    assert caught.value.defect is defect


def test_the_production_inspector_fails_closed_on_a_file_it_cannot_answer_about(
    tmp_path: Path,
) -> None:
    """No "checked where supported" path exists: an unanswerable file is a refusal."""
    with pytest.raises(rb.RuntimeBindingError) as caught:
        rb.windows_file_security(tmp_path / "absent.json")
    assert caught.value.defect is rb.RuntimeBindingDefect.SECURITY_UNVERIFIABLE


def test_an_inspector_answering_with_the_wrong_type_refuses(tmp_path: Path) -> None:
    with pytest.raises(rb.RuntimeBindingError) as caught:
        _load(tmp_path, security_of=lambda _path: object())  # type: ignore[arg-type,return-value]
    assert caught.value.defect is rb.RuntimeBindingDefect.SECURITY_UNVERIFIABLE


def test_a_file_replaced_between_the_check_and_the_read_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The identity is taken before the read and confirmed after it."""
    root = _private_root(tmp_path)
    target = root / "assessment.json"
    original = Path.read_bytes

    def _swap(self: Path) -> bytes:
        content = original(self)
        if self == target:
            # A different document, of a different length, written by somebody else in
            # the window between the ownership check and this read.
            self.write_bytes(
                rb.canonical_binding_bytes(_document(licensed_bucket_name=SWAPPED_BUCKET))
            )
        return content

    monkeypatch.setattr(Path, "read_bytes", _swap)
    with pytest.raises(rb.RuntimeBindingError) as caught:
        _load(tmp_path, path_override=str(target))
    assert caught.value.defect is rb.RuntimeBindingDefect.FILE_CHANGED_DURING_READ


def test_security_that_changes_between_the_two_readings_refuses(tmp_path: Path) -> None:
    states = [_security(), _security(allow_principals=(CURRENT, EVERYONE))]

    def _drifting(_path: Path) -> rb.FileSecurity:
        return states.pop(0) if states else _security()

    with pytest.raises(rb.RuntimeBindingError) as caught:
        _load(tmp_path, security_of=_drifting)
    assert caught.value.defect is rb.RuntimeBindingDefect.FILE_CHANGED_DURING_READ


# -- bytes, encoding and structure --------------------------------------------


def test_an_empty_file_refuses(tmp_path: Path) -> None:
    assert _refused(tmp_path, raw=b"").value.defect is rb.RuntimeBindingDefect.FILE_EMPTY


def test_an_oversized_file_refuses(tmp_path: Path) -> None:
    oversized = b"{" + b" " * (rb.MAX_ASSESSMENT_RUNTIME_BINDING_BYTES + 1) + b"}"
    assert _refused(tmp_path, raw=oversized).value.defect is rb.RuntimeBindingDefect.FILE_TOO_LARGE


def test_a_byte_order_mark_refuses(tmp_path: Path) -> None:
    raw = b"\xef\xbb\xbf" + rb.canonical_binding_bytes(_document())
    assert _refused(tmp_path, raw=raw).value.defect is rb.RuntimeBindingDefect.ENCODING_INVALID


def test_invalid_utf8_refuses(tmp_path: Path) -> None:
    assert _refused(tmp_path, raw=b"\xff\xfe{}").value.defect is (
        rb.RuntimeBindingDefect.ENCODING_INVALID
    )


def test_malformed_json_refuses(tmp_path: Path) -> None:
    assert _refused(tmp_path, raw=b"{").value.defect is rb.RuntimeBindingDefect.DOCUMENT_MALFORMED


@pytest.mark.parametrize("payload", [b"[]", b'"text"', b"12", b"null", b"true"])
def test_a_non_object_document_refuses(tmp_path: Path, payload: bytes) -> None:
    assert _refused(tmp_path, raw=payload).value.defect is (
        rb.RuntimeBindingDefect.DOCUMENT_MALFORMED
    )


def test_a_duplicate_top_level_key_refuses(tmp_path: Path) -> None:
    text = json.dumps(_document())
    doubled = text[:-1] + f', "licensed_bucket_name": "{OTHER_BUCKET}"' + "}"
    assert _refused(tmp_path, raw=doubled.encode("utf-8")).value.defect is (
        rb.RuntimeBindingDefect.DUPLICATE_KEY
    )


def test_a_duplicate_provenance_key_refuses(tmp_path: Path) -> None:
    text = json.dumps(_document())
    doubled = text.replace(
        f'"implementation_commit": "{COMMIT}"',
        f'"implementation_commit": "{COMMIT}", "implementation_commit": "{TREE}"',
        1,
    )
    assert _refused(tmp_path, raw=doubled.encode("utf-8")).value.defect is (
        rb.RuntimeBindingDefect.DUPLICATE_KEY
    )


# -- the field rules -----------------------------------------------------------

DOCUMENT_REFUSALS: Final[tuple[tuple[str, dict[str, Any], rb.RuntimeBindingDefect], ...]] = (
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
        "another contract id",
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
        "the acquisition profile",
        {"assessment_profile": rb.EXPECTED_ACQUISITION_PROFILE},
        rb.RuntimeBindingDefect.PROFILE_UNEXPECTED,
    ),
    (
        "the foundation profile",
        {"assessment_profile": "kalpamani-foundation"},
        rb.RuntimeBindingDefect.PROFILE_UNEXPECTED,
    ),
    (
        "a malformed account",
        {"target_account_id": "0000000000"},
        rb.RuntimeBindingDefect.ACCOUNT_MALFORMED,
    ),
    (
        "an account that is not a string",
        {"target_account_id": 0},
        rb.RuntimeBindingDefect.FIELD_MALFORMED,
    ),
    (
        "a malformed bucket",
        {"licensed_bucket_name": "s3://synthetic"},
        rb.RuntimeBindingDefect.BUCKET_NAME_MALFORMED,
    ),
    (
        "a malformed provenance block",
        {"provenance": {"implementation_commit": COMMIT}},
        rb.RuntimeBindingDefect.FIELD_MISSING,
    ),
    (
        "a provenance value of the wrong grammar",
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
        "provenance that is not an object",
        {"provenance": []},
        rb.RuntimeBindingDefect.PROVENANCE_MALFORMED,
    ),
    (
        "an unknown extra field",
        {"actor": "assessment"},
        rb.RuntimeBindingDefect.FIELD_UNKNOWN,
    ),
)


@pytest.mark.parametrize(
    ("overrides", "defect"),
    [(overrides, defect) for _label, overrides, defect in DOCUMENT_REFUSALS],
    ids=[label for label, _overrides, _defect in DOCUMENT_REFUSALS],
)
def test_a_document_breaking_the_contract_refuses(
    tmp_path: Path, overrides: dict[str, Any], defect: rb.RuntimeBindingDefect
) -> None:
    raw = rb.canonical_binding_bytes(_document(**overrides))
    assert _refused(tmp_path, raw=raw).value.defect is defect


@pytest.mark.parametrize("missing", sorted(rb._ASSESSMENT_DOCUMENT_FIELDS))
def test_every_missing_top_level_field_refuses(tmp_path: Path, missing: str) -> None:
    document = _document()
    del document[missing]
    raw = rb.canonical_binding_bytes(document)
    assert _refused(tmp_path, raw=raw).value.defect is rb.RuntimeBindingDefect.FIELD_MISSING


def test_the_document_parser_reads_no_file(tmp_path: Path) -> None:
    """The parser is separable, which is what makes every rule above testable."""
    opened: list[str] = []
    real_open = Path.open

    def _watched(self: Path, *args: Any, **kwargs: Any) -> Any:
        opened.append(str(self))
        return real_open(self, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Path, "open", _watched)
        assert rb.parse_assessment_runtime_binding(_document()).licensed_bucket_name == BUCKET
    assert opened == []


def test_no_refusal_carries_a_private_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every canary, against every surface a refusal could reach."""
    outside = tmp_path / "elsewhere.json"
    outside.write_bytes(rb.canonical_binding_bytes(_document()))
    with pytest.raises(rb.RuntimeBindingError) as caught:
        _load(tmp_path, path_override=str(outside))
    printed = capsys.readouterr()
    for surface in (str(caught.value), repr(caught.value), printed.out, printed.err):
        for canary in (ACCOUNT, BUCKET, CURRENT, COMMIT, TREE, ENVELOPE, str(outside)):
            assert canary not in surface


# ---------------------------------------------------------------------------
# The materialization gate
# ---------------------------------------------------------------------------


class _Recorder:
    """A synthetic private-artifact writer that records rather than writes."""

    def __init__(self, *, fail: bool = False, returns: Any = None) -> None:
        self.writes: list[tuple[str, bytes]] = []
        self.fail = fail
        self.returns = returns

    def __call__(self, *, destination: str, payload: bytes) -> Path:
        if self.fail:
            raise OSError("the artifact was not created")
        self.writes.append((destination, payload))
        return Path(destination) if self.returns is None else self.returns


class _Bin:
    """A synthetic rollback that records what it was asked to remove."""

    def __init__(self, *, fail: bool = False) -> None:
        self.removed: list[Path] = []
        self.fail = fail

    def __call__(self, path: Path) -> None:
        self.removed.append(path)
        if self.fail:
            raise OSError("the artifact could not be removed")


class _Verifier:
    """A synthetic re-read that answers with whatever a test asks it to."""

    def __init__(
        self,
        bucket: str | None = BUCKET,
        account: str | None = ACCOUNT,
        *,
        fail: bool = False,
    ) -> None:
        self.calls: list[str] = []
        self.bucket = bucket
        self.account = account
        self.fail = fail

    def __call__(self, *, destination: str) -> Any:
        self.calls.append(destination)
        if self.fail:
            raise rb.RuntimeBindingError(rb.RuntimeBindingDefect.FILE_UNREADABLE)
        return rb.QualificationAssessmentRuntimeBinding(
            target_account_id=self.account if self.account is not None else OTHER_ACCOUNT,
            licensed_bucket_name=self.bucket if self.bucket is not None else OTHER_BUCKET,
            partition=rb.EXPECTED_PARTITION,
            region=rb.EXPECTED_REGION,
            assessment_profile=rb.EXPECTED_ASSESSMENT_PROFILE,
        )


def _environment_binding(**overrides: Any) -> rb.QualificationEnvironmentBinding:
    settled: dict[str, Any] = {
        "target_account_id": ACCOUNT,
        "licensed_bucket_name": BUCKET,
        "partition": rb.EXPECTED_PARTITION,
        "region": rb.EXPECTED_REGION,
        "digest": ENVELOPE,
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
    destination: str = r"C:\synthetic\KalpaMani\private\assessment.json",
    account: str | None = ACCOUNT,
    loader: Callable[..., Any] | None = None,
    module: Any = None,
    bin_: _Bin | None = None,
) -> tuple[Any, _Recorder, _Verifier]:
    target = gate if module is None else module
    sink = recorder if recorder is not None else _Recorder()
    checker = verifier if verifier is not None else _Verifier()
    outcome = target.materialize_assessment_binding(
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
        verify_assessment_binding=checker,
        discard_artifact=_Bin() if bin_ is None else bin_,
    )
    return outcome, sink, checker


def test_a_materialization_writes_one_verified_assessment_binding() -> None:
    outcome, sink, checker = _materialize()
    assert outcome is gate.MaterializationOutcome.COMPLETED
    assert len(sink.writes) == 1
    assert len(checker.calls) == 1

    document = json.loads(sink.writes[0][1].decode("utf-8"))
    binding = rb.parse_assessment_runtime_binding(document)
    assert binding.licensed_bucket_name == BUCKET
    assert binding.target_account_id == ACCOUNT
    assert document["assessment_profile"] == rb.EXPECTED_ASSESSMENT_PROFILE
    assert "acquisition_profile" not in document


def test_the_written_binding_carries_the_digest_of_the_source_bytes(tmp_path: Path) -> None:
    """End to end: a real synthetic file in, its digest in the written field."""
    root = _private_root(tmp_path)
    source = root / "environment.json"
    payload = rb.canonical_binding_bytes(
        {
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
                "outputs_digest": ENVELOPE,
            },
        }
    )
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
    assert provenance["implementation_commit"] == gate.IMPLEMENTATION_COMMIT
    assert provenance["implementation_tree"] == gate.IMPLEMENTATION_TREE


def test_the_payload_is_the_canonical_serialisation() -> None:
    _outcome, sink, _checker = _materialize()
    document = json.loads(sink.writes[0][1].decode("utf-8"))
    assert sink.writes[0][1] == rb.canonical_binding_bytes(document)


MATERIALIZATION_REFUSALS: Final[tuple[tuple[str, dict[str, Any], Any], ...]] = (
    (
        "no authorization",
        {"authorization": object()},
        gate.MaterializationOutcome.REFUSED_NOT_AUTHORIZED,
    ),
    (
        "under a test runner",
        {"modules": {"pytest": object()}},
        gate.MaterializationOutcome.REFUSED_EXECUTION_CONTEXT,
    ),
    (
        "in continuous integration",
        {"env": {"GITHUB_ACTIONS": "true"}},
        gate.MaterializationOutcome.REFUSED_EXECUTION_CONTEXT,
    ),
    (
        "with no source path",
        {"source": "  "},
        gate.MaterializationOutcome.REFUSED_SOURCE_PATH,
    ),
    (
        "with no governed account binding",
        {"account": None},
        gate.MaterializationOutcome.REFUSED_EXPECTED_ACCOUNT,
    ),
    (
        "with no destination",
        {"destination": ""},
        gate.MaterializationOutcome.REFUSED_DESTINATION,
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
    with pytest.raises(gate.MaterializationError) as caught:
        _materialize(recorder=sink, **overrides)
    assert caught.value.outcome is outcome
    assert sink.writes == []


ENVIRONMENT_REFUSALS: Final[tuple[tuple[str, dict[str, Any]], ...]] = (
    ("a foreign account", {"target_account_id": OTHER_ACCOUNT}),
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
    with pytest.raises(gate.MaterializationError) as caught:
        _materialize(recorder=sink, loader=lambda **_kwargs: _environment_binding(**overrides))
    assert caught.value.outcome is gate.MaterializationOutcome.REFUSED_ENVIRONMENT_BINDING
    assert sink.writes == []


def test_an_unsafe_source_stops_the_gate() -> None:
    """A Source B the trust boundary refuses is a refusal here, and no file is made."""

    def _refusing(**_kwargs: Any) -> Any:
        raise rb.RuntimeBindingError(rb.RuntimeBindingDefect.ACL_NOT_EXCLUSIVE)

    sink = _Recorder()
    with pytest.raises(gate.MaterializationError) as caught:
        _materialize(recorder=sink, loader=_refusing)
    assert caught.value.outcome is gate.MaterializationOutcome.REFUSED_ENVIRONMENT_BINDING
    assert sink.writes == []


def test_a_loader_answering_with_the_wrong_type_refuses() -> None:
    sink = _Recorder()
    with pytest.raises(gate.MaterializationError) as caught:
        _materialize(recorder=sink, loader=lambda **_kwargs: object())
    assert caught.value.outcome is gate.MaterializationOutcome.REFUSED_ENVIRONMENT_BINDING
    assert sink.writes == []


def test_a_failed_write_is_reported_and_nothing_is_verified() -> None:
    sink = _Recorder(fail=True)
    checker = _Verifier()
    with pytest.raises(gate.MaterializationError) as caught:
        _materialize(recorder=sink, verifier=checker)
    assert caught.value.outcome is gate.MaterializationOutcome.REFUSED_WRITE
    assert checker.calls == []


VERIFICATION_FAILURES: Final[tuple[tuple[str, _Verifier], ...]] = (
    ("the artifact will not load", _Verifier(fail=True)),
    ("it names another bucket", _Verifier(bucket=OTHER_BUCKET)),
    ("it names another account", _Verifier(account=OTHER_ACCOUNT)),
)


@pytest.mark.parametrize(
    "checker",
    [checker for _label, checker in VERIFICATION_FAILURES],
    ids=[label for label, _checker in VERIFICATION_FAILURES],
)
def test_an_artifact_that_does_not_verify_is_reported_and_removed(checker: _Verifier) -> None:
    """The refusal and the rollback are one event.

    The shared writer rolls back its own failures; this is the one it cannot see -- a
    file that satisfied the composer and the descriptor and that the production loader
    will not accept. Leaving it behind would put an unusable private artifact exactly
    where a later, separately authorized run reads one.
    """
    sink = _Recorder()
    disposal = _Bin()
    with pytest.raises(gate.MaterializationError) as caught:
        _materialize(recorder=sink, verifier=checker, bin_=disposal)
    assert caught.value.outcome is gate.MaterializationOutcome.REFUSED_VERIFICATION
    assert disposal.removed == [Path(sink.writes[0][0])]


def test_a_verified_artifact_is_not_removed() -> None:
    """The rollback is on the refusal path and nowhere else."""
    disposal = _Bin()
    outcome, _sink, _checker = _materialize(bin_=disposal)
    assert outcome is gate.MaterializationOutcome.COMPLETED
    assert disposal.removed == []


def test_a_writer_answering_with_something_other_than_a_path_is_reported() -> None:
    """A writer that did not return the artifact it created cannot have it rolled back."""
    disposal = _Bin()
    with pytest.raises(gate.MaterializationError) as caught:
        _materialize(recorder=_Recorder(returns="not-a-path"), bin_=disposal)
    assert caught.value.outcome is gate.MaterializationOutcome.REFUSED_VERIFICATION


def test_a_rollback_that_fails_does_not_change_the_refusal() -> None:
    """A file that cannot be removed is still a refusal, and still that refusal."""
    disposal = _Bin(fail=True)
    with pytest.raises(gate.MaterializationError) as caught:
        _materialize(verifier=_Verifier(bucket=OTHER_BUCKET), bin_=disposal)
    assert caught.value.outcome is gate.MaterializationOutcome.REFUSED_VERIFICATION
    assert len(disposal.removed) == 1


def test_a_failed_write_rolls_nothing_back() -> None:
    """Nothing was created, so there is nothing this command may unlink."""
    disposal = _Bin()
    with pytest.raises(gate.MaterializationError) as caught:
        _materialize(recorder=_Recorder(fail=True), bin_=disposal)
    assert caught.value.outcome is gate.MaterializationOutcome.REFUSED_WRITE
    assert disposal.removed == []


def test_the_production_rollback_removes_only_the_named_file(tmp_path: Path) -> None:
    """The real disposal, against real files, on a path this command created itself."""
    root = _private_root(tmp_path)
    doomed = root / "assessment.json"
    neighbour = root / "keep.json"
    doomed.write_bytes(b"{}")
    neighbour.write_bytes(b"{}")
    gate._discard_artifact(doomed)
    assert not doomed.exists()
    assert neighbour.exists()
    # A second removal of the same path is silent: a failure to remove must never
    # mask or change the refusal that caused it.
    gate._discard_artifact(doomed)


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
    assert outcome is gate.MaterializationOutcome.COMPLETED


def test_the_gate_refuses_by_default_and_its_flag_is_its_own() -> None:
    assert gate.main([]) == gate._EXIT_CODES[gate.MaterializationOutcome.REFUSED_NOT_AUTHORIZED]
    acquire_gate = ACQUIRE_GATE_PATH.read_text(encoding="utf-8")
    assert gate.AUTHORIZATION_FLAG not in acquire_gate
    assert gate.AUTHORIZATION_FLAG not in ASSESS_PATH.read_text(encoding="utf-8")


@pytest.mark.parametrize("option", ["--bucket", "--account", "--path", "--actor", "--force"])
def test_the_gate_refuses_every_path_and_value_option(option: str) -> None:
    assert option in gate.REFUSED_OPTIONS
    assert gate.main([option]) == gate._EXIT_CODES[gate.MaterializationOutcome.REFUSED_OPTION]


def test_the_exit_status_map_is_total_over_the_outcome_vocabulary() -> None:
    assert set(gate._EXIT_CODES) == set(gate.MaterializationOutcome)
    zeros = [outcome for outcome, code in gate._EXIT_CODES.items() if code == 0]
    assert zeros == [gate.MaterializationOutcome.COMPLETED]


def test_no_outcome_sentence_reads_as_permission_or_names_a_value() -> None:
    """Every sentence either refuses or reports completion, and none reads as licence.

    ``authorized`` is deliberately absent from the refused words: the default refusal
    is *"not authorized"*, which is the opposite of permission, and refusing the word
    would refuse the sentence that carries the strongest denial in the vocabulary.
    """
    for outcome in gate.MaterializationOutcome:
        lowered = outcome.value.lower()
        assert "refused" in lowered or outcome is gate.MaterializationOutcome.COMPLETED
        for forbidden in ("ready", "approved", "proceed", "qualified", "bound", "verdict"):
            assert forbidden not in lowered, outcome
        for canary in (ACCOUNT, BUCKET, CURRENT, ENVELOPE):
            assert canary not in outcome.value


# ---------------------------------------------------------------------------
# Isolation -- who may reach what
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


def test_the_gate_names_no_terraform_reach() -> None:
    """It reads a private file and the local account binding, and nothing else."""
    imported = _imported_names(GATE_PATH)
    assert "tf_outputs" not in imported
    assert "expected_account" in imported
    source = GATE_PATH.read_text(encoding="utf-8")
    for forbidden in ("tf_outputs", "backend_settings", "-chdir=", "subprocess", "boto3"):
        assert forbidden not in source, forbidden


def test_the_two_gates_write_different_artifacts() -> None:
    """No actor switch anywhere: each gate composes one kind and never the other."""
    assessment = GATE_PATH.read_text(encoding="utf-8")
    acquisition = ACQUIRE_GATE_PATH.read_text(encoding="utf-8")
    assert "ASSESSMENT_RUNTIME_BINDING_KIND" in assessment
    assert "ASSESSMENT_RUNTIME_BINDING_KIND" not in acquisition
    assert "EXPECTED_ACQUISITION_PROFILE" not in assessment
    assert "EXPECTED_ASSESSMENT_PROFILE" not in acquisition
    assert "RUNTIME_BINDING_KIND" in acquisition


def test_neither_entry_point_names_the_assessment_gate() -> None:
    """Necessary and not sufficient -- the call-graph guards are the semantic ones."""
    for entry in (ASSESS_PATH, ACQUIRE_PATH):
        source = entry.read_text(encoding="utf-8")
        for tool in (
            "qualification_assessment_binding_materialize",
            "qualification_runtime_binding_materialize",
            "qualification_environment_binding_capture",
            "qualification_private_artifacts",
            "load_environment_binding",
        ):
            assert tool not in source, (entry.name, tool)


def test_the_gate_reuses_the_one_writer_rather_than_its_own() -> None:
    source = GATE_PATH.read_text(encoding="utf-8")
    assert "write_private_artifact" in source
    assert "O_EXCL" not in source
    assert "SetNamedSecurityInfoW" not in source
    assert "O_EXCL" in WRITER_PATH.read_text(encoding="utf-8")


def test_the_contract_module_declares_the_assessment_binding_beside_the_others() -> None:
    contract = CONTRACT_PATH.read_text(encoding="utf-8")
    assert "def parse_assessment_runtime_binding" in contract
    assert "def load_assessment_runtime_binding" in contract
    assert f'"{rb.ASSESSMENT_RUNTIME_BINDING_KIND}"' in contract
    assert f'"{rb.ASSESSMENT_RUNTIME_BINDING_CONTRACT_ID}"' in contract


def test_the_contract_module_writes_nothing_and_enumerates_nothing() -> None:
    tree = ast.parse(CONTRACT_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr | ast.Assign):
            continue
    code = ast.unparse(tree)
    for token in ("glob(", "rglob(", "iterdir(", "listdir(", "scandir(", "walk("):
        assert token not in code, token
    for token in ("write_text", "write_bytes", "mkdir", "tempfile", "boto3", "subprocess"):
        assert token not in code, token


def test_the_environment_variable_name_is_spelled_in_the_two_places_that_state_it() -> None:
    """The contract module declares it; the entry point restates its own contract."""
    declaring = [
        path
        for path in (CONTRACT_PATH, ASSESS_PATH, GATE_PATH, ACQUIRE_GATE_PATH, WRITER_PATH)
        if f'"{rb.ASSESSMENT_RUNTIME_BINDING_ENV_VAR}"' in path.read_text(encoding="utf-8")
    ]
    assert declaring == [CONTRACT_PATH, ASSESS_PATH]


# ---------------------------------------------------------------------------
# Mutations -- each guard, watched failing
# ---------------------------------------------------------------------------


def _mutated_source(path: Path, replacements: tuple[tuple[str, str], ...]) -> str:
    source = path.read_text(encoding="utf-8")
    for old, new in replacements:
        assert source.count(old) == 1, old
        source = source.replace(old, new, 1)
    return source


def _mutant(name: str, path: Path, replacements: tuple[tuple[str, str], ...]) -> ModuleType:
    """One module built from mutated source. **In memory only.**

    Registered in ``sys.modules`` *before* execution, and removed afterwards: the
    contract module declares dataclasses under ``from __future__ import annotations``,
    and ``dataclasses`` resolves an annotation through ``sys.modules[cls.__module__]``
    while the class body runs.
    """
    source = _mutated_source(path, replacements)
    module = ModuleType(name)
    module.__file__ = str(path)
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    sys.modules[name] = module
    try:
        exec(compile(source, str(path), "exec"), module.__dict__)  # noqa: S102 - the mutation
    finally:
        sys.modules.pop(name, None)
    return module


ACCOUNT_CONSISTENCY: Final[tuple[tuple[str, str], ...]] = (
    (
        "    if environment.target_account_id != account:\n"
        "        raise MaterializationError("
        "MaterializationOutcome.REFUSED_ENVIRONMENT_BINDING) from None\n",
        "",
    ),
)

ACTOR_SEPARATION: Final[tuple[tuple[str, str], ...]] = (
    ('"assessment_profile": EXPECTED_ASSESSMENT_PROFILE,', '"assessment_profile": "anything",'),
)

SOURCE_DIGEST: Final[tuple[tuple[str, str], ...]] = (
    (
        '"environment_binding_sha256": environment.digest,',
        f'"environment_binding_sha256": "{ENVELOPE}",',
    ),
)

POST_WRITE_VERIFICATION: Final[tuple[tuple[str, str], ...]] = (
    (
        '    if getattr(verified, "licensed_bucket_name", None) '
        "!= environment.licensed_bucket_name:"
        + chr(10)
        + "        raise _refuse_verification() from None"
        + chr(10),
        "",
    ),
)

ACL_ENFORCEMENT: Final[tuple[tuple[str, str], ...]] = (
    (
        "    if security.allow_principals != (security.current_principal,):\n"
        "        raise _refuse(RuntimeBindingDefect.ACL_NOT_EXCLUSIVE) from None\n",
        "",
    ),
)

ACCOUNT_GRAMMAR: Final[tuple[tuple[str, str], ...]] = (
    (
        '    account = _exact_string(document, "target_account_id")\n'
        "    if not _ACCOUNT_ID.match(account):\n"
        "        raise _refuse(RuntimeBindingDefect.ACCOUNT_MALFORMED) from None\n\n"
        '    bucket = _exact_string(document, "licensed_bucket_name")\n'
        "    if not _BUCKET_NAME.match(bucket):\n"
        "        raise _refuse(RuntimeBindingDefect.BUCKET_NAME_MALFORMED) from None\n\n"
        '    _validate_provenance(document["provenance"])\n\n'
        "    return QualificationAssessmentRuntimeBinding(",
        '    account = _exact_string(document, "target_account_id")\n'
        '    bucket = _exact_string(document, "licensed_bucket_name")\n'
        '    _validate_provenance(document["provenance"])\n\n'
        "    return QualificationAssessmentRuntimeBinding(",
    ),
)

PROFILE_ENFORCEMENT: Final[tuple[tuple[str, str], ...]] = (
    (
        '    if _exact_string(document, "assessment_profile") != EXPECTED_ASSESSMENT_PROFILE:\n'
        "        raise _refuse(RuntimeBindingDefect.PROFILE_UNEXPECTED) from None\n",
        "",
    ),
)


def test_every_mutation_target_appears_exactly_once_in_the_real_source() -> None:
    """A mutation that silently matched nothing would make every test below pass."""
    for path, replacements in (
        (GATE_PATH, ACCOUNT_CONSISTENCY),
        (GATE_PATH, ACTOR_SEPARATION),
        (GATE_PATH, SOURCE_DIGEST),
        (GATE_PATH, POST_WRITE_VERIFICATION),
        (CONTRACT_PATH, ACL_ENFORCEMENT),
        (CONTRACT_PATH, ACCOUNT_GRAMMAR),
        (CONTRACT_PATH, PROFILE_ENFORCEMENT),
    ):
        mutated = _mutated_source(path, replacements)
        assert mutated != path.read_text(encoding="utf-8")
        ast.parse(mutated)


def test_removing_the_account_consistency_is_caught() -> None:
    """Real code refuses a foreign account; the mutant writes it."""
    with pytest.raises(gate.MaterializationError):
        _materialize(loader=lambda **_kwargs: _environment_binding(target_account_id=OTHER_ACCOUNT))

    mutant = _mutant("_assessment_gate_no_account_check", GATE_PATH, ACCOUNT_CONSISTENCY)
    _outcome, sink, _checker = _materialize(
        module=mutant,
        loader=lambda **_kwargs: _environment_binding(target_account_id=OTHER_ACCOUNT),
        verifier=_Verifier(account=OTHER_ACCOUNT),
    )
    assert json.loads(sink.writes[0][1].decode("utf-8"))["target_account_id"] == OTHER_ACCOUNT


def test_removing_the_actor_pin_is_caught() -> None:
    """The written profile is a compiled constant; a mutant that chose one is refused."""
    mutant = _mutant("_assessment_gate_no_actor_pin", GATE_PATH, ACTOR_SEPARATION)
    with pytest.raises(mutant.MaterializationError) as caught:
        _materialize(module=mutant)
    assert caught.value.outcome is mutant.MaterializationOutcome.REFUSED_DOCUMENT


def test_removing_the_source_digest_binding_is_caught(tmp_path: Path) -> None:
    """The digest must come from the bytes that were read, not from a constant."""
    root = _private_root(tmp_path)
    source = root / "environment.json"
    payload = rb.canonical_binding_bytes(
        {
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
                "outputs_digest": ENVELOPE,
            },
        }
    )
    source.write_bytes(payload)

    def _loader(*, path: str, expected_account: str | None) -> Any:
        return rb.load_environment_binding(
            path=path,
            expected_account=expected_account,
            root_source=lambda: root,
            security_of=lambda _path: _security(),
        )

    _outcome, real, _checker = _materialize(source=str(source), loader=_loader)
    assert json.loads(real.writes[0][1].decode("utf-8"))["provenance"][
        "environment_binding_sha256"
    ] == rb.sha256_hex(payload)

    mutant = _mutant("_assessment_gate_no_digest", GATE_PATH, SOURCE_DIGEST)
    _outcome, sink, _checker = _materialize(module=mutant, source=str(source), loader=_loader)
    assert json.loads(sink.writes[0][1].decode("utf-8"))["provenance"][
        "environment_binding_sha256"
    ] != rb.sha256_hex(payload)


def test_removing_the_post_write_verification_is_caught() -> None:
    """Real code refuses an artifact that reloads as something else; the mutant does not."""
    with pytest.raises(gate.MaterializationError):
        _materialize(verifier=_Verifier(bucket=OTHER_BUCKET))

    mutant = _mutant("_assessment_gate_no_verify", GATE_PATH, POST_WRITE_VERIFICATION)
    outcome, _sink, _checker = _materialize(module=mutant, verifier=_Verifier(bucket=OTHER_BUCKET))
    assert outcome is mutant.MaterializationOutcome.COMPLETED


def test_removing_the_access_control_verification_is_caught(tmp_path: Path) -> None:
    """Real code refuses a world-readable binding; the mutant loads it."""
    with pytest.raises(rb.RuntimeBindingError):
        _load(tmp_path, security=_security(allow_principals=(CURRENT, EVERYONE)))

    mutant = _mutant("_binding_contract_no_acl", CONTRACT_PATH, ACL_ENFORCEMENT)
    root = _private_root(tmp_path)
    target = root / "assessment.json"
    target.write_bytes(rb.canonical_binding_bytes(_document()))
    loosened = mutant.FileSecurity(
        current_principal=CURRENT,
        owner=CURRENT,
        inheritance_disabled=True,
        allow_principals=(CURRENT, EVERYONE),
        deny_principals=(),
    )
    binding = mutant.load_assessment_runtime_binding(
        path_source=lambda: str(target),
        root_source=lambda: root,
        security_of=lambda _path: loosened,
    )
    assert binding.licensed_bucket_name == BUCKET


def test_removing_the_account_grammar_is_caught(tmp_path: Path) -> None:
    """Real code refuses a ten-digit account; the mutant returns it."""
    malformed = _document(target_account_id="0000000000")
    with pytest.raises(rb.RuntimeBindingError) as caught:
        rb.parse_assessment_runtime_binding(malformed)
    assert caught.value.defect is rb.RuntimeBindingDefect.ACCOUNT_MALFORMED

    mutant = _mutant("_binding_contract_no_account_grammar", CONTRACT_PATH, ACCOUNT_GRAMMAR)
    assert mutant.parse_assessment_runtime_binding(malformed).target_account_id == "0000000000"


def test_removing_the_actor_profile_check_is_caught() -> None:
    """Real code refuses the acquisition profile; the mutant admits it."""
    swapped = _document(assessment_profile=rb.EXPECTED_ACQUISITION_PROFILE)
    with pytest.raises(rb.RuntimeBindingError) as caught:
        rb.parse_assessment_runtime_binding(swapped)
    assert caught.value.defect is rb.RuntimeBindingDefect.PROFILE_UNEXPECTED

    mutant = _mutant("_binding_contract_no_profile_pin", CONTRACT_PATH, PROFILE_ENFORCEMENT)
    assert mutant.parse_assessment_runtime_binding(swapped) is not None


def test_no_mutation_reaches_the_repository_source() -> None:
    """Every mutation above is a string. The files on disk are never rewritten."""
    assert "target_account_id != account" in GATE_PATH.read_text(encoding="utf-8")
    assert "ACL_NOT_EXCLUSIVE" in CONTRACT_PATH.read_text(encoding="utf-8")
    assert "PROFILE_UNEXPECTED" in CONTRACT_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Nothing private, and no restated grammar
# ---------------------------------------------------------------------------

TRACKED_SURFACES: Final[tuple[Path, ...]] = (CONTRACT_PATH, GATE_PATH, ASSESS_PATH)


@pytest.mark.parametrize("path", TRACKED_SURFACES, ids=lambda path: path.name)
def test_no_surface_carries_a_private_identifier(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for marker in ("arn:aws:", "amazonaws.com", "AKIA", ".amazonaws", "awsapps.com"):
        assert marker not in text, marker
    assert re.search(r"\b\d{12}\b", text) is None
    assert "sap4n" not in text


def test_this_suite_restates_no_production_grammar() -> None:
    """A test that reimplements a rule tests its own copy of it.

    Every field rule here is asked of the production validator, so a compiled pattern
    of this file's own would be a second grammar nobody reconciled with the first. The
    one ``re`` call this file makes is the private-identifier scan above, which
    searches rather than compiles.
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


def test_this_suite_names_no_contract_value_of_its_own() -> None:
    """Every kind, contract id and variable comes from the production constants.

    A literal copy would keep passing after the production value moved, which is the
    failure mode a fixture built from constants cannot have.
    """
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and type(node.value) is str
    }
    for governed in (
        rb.ASSESSMENT_RUNTIME_BINDING_KIND,
        rb.ASSESSMENT_RUNTIME_BINDING_CONTRACT_ID,
        rb.ASSESSMENT_RUNTIME_BINDING_ENV_VAR,
        rb.EXPECTED_ASSESSMENT_PROFILE,
        rb.EXPECTED_ACQUISITION_PROFILE,
    ):
        assert governed not in literals, governed


def test_the_private_root_is_never_the_real_one(tmp_path: Path) -> None:
    """Every load here runs against an injected synthetic root."""
    root = _private_root(tmp_path)
    assert root.is_absolute()
    assert "LOCALAPPDATA" not in str(root)
    assert stat.S_ISDIR(root.lstat().st_mode)
