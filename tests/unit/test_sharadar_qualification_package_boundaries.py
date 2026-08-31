"""Structural boundaries of the qualification package, checked in the import graph.

Every separation this architecture relies on is asserted here as a property of what
imports what, not as a rule somebody has to remember:

- the ingestion path cannot import the qualification package, so the acquisition path
  stays parser-free;
- the qualification package cannot import or copy the public-test-key harness;
- the acquisition composition cannot reach the parser or the evaluator;
- the assessment composition cannot reach a credential, a secrets boundary or a
  provider transport;
- no module under ``src/`` constructs an AWS SDK client.

These are AST scans over the real files. A comment claiming a boundary is not a
boundary; an import that fails to exist is.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src" / "kalpamani"
QUALIFY = SRC / "data" / "qualify"
INGEST = SRC / "data" / "ingest"
SCRIPTS = REPO_ROOT / "scripts"

QUALIFY_MODULES = sorted(QUALIFY.rglob("*.py"))
INGEST_MODULES = sorted(INGEST.rglob("*.py"))

#: The public-test-key harness. Untouched, unimported and unauthorized to execute.
HARNESS_MODULE = "sharadar_private_qualification"


def _imports(path: Path) -> set[str]:
    """Every module name imported anywhere in ``path``, at any nesting depth."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _executable(path: Path) -> str:
    """The module with docstrings removed, so prose cannot satisfy a check."""
    tree = ast.parse(_source(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                body.pop(0)
    return ast.unparse(tree)


def test_the_qualification_package_exists_and_is_outside_the_ingestion_path() -> None:
    assert QUALIFY.is_dir()
    assert QUALIFY.parent.name == "data"
    assert QUALIFY.name == "qualify"
    assert not str(QUALIFY).startswith(str(INGEST))


# -- the ingestion path cannot import the qualification package ---------------


@pytest.mark.parametrize("path", INGEST_MODULES, ids=lambda path: path.name)
def test_no_ingestion_module_imports_the_qualification_package(path: Path) -> None:
    for imported in _imports(path):
        assert "data.qualify" not in imported
        assert not imported.startswith("kalpamani.data.qualify")


@pytest.mark.parametrize("path", INGEST_MODULES, ids=lambda path: path.name)
def test_no_ingestion_module_names_the_qualification_package(path: Path) -> None:
    assert "data.qualify" not in _executable(path)


# -- the qualification package cannot import or copy the harness --------------


@pytest.mark.parametrize("path", QUALIFY_MODULES, ids=lambda path: path.name)
def test_no_qualification_module_imports_the_public_test_key_harness(path: Path) -> None:
    assert HARNESS_MODULE not in _imports(path)
    assert HARNESS_MODULE not in _source(path)


def test_the_public_test_key_harness_is_untouched_by_this_slice() -> None:
    harness = SCRIPTS / f"{HARNESS_MODULE}.py"
    assert harness.is_file()
    # It knows nothing of this package, in either direction.
    assert "data.qualify" not in _source(harness)
    assert "sharadar_empirical_qualification" not in _source(harness)
    assert "sharadar_qualification_assessment" not in _source(harness)


@pytest.mark.parametrize("path", QUALIFY_MODULES, ids=lambda path: path.name)
def test_no_qualification_module_copies_a_harness_function_name(path: Path) -> None:
    # A copy is as forbidden as an import. These are the harness's own P-test entry
    # point names; none may appear here under any spelling.
    for copied in ("run_p1", "run_p2", "p_test", "PROCEED", "HOLD", "REJECT"):
        assert copied not in _source(path)


# -- the acquisition path stays parser-free -----------------------------------


ACQUISITION = QUALIFY / "sharadar" / "acquisition.py"
ASSESSMENT = QUALIFY / "sharadar" / "assessment.py"


def test_the_acquisition_composition_imports_neither_parser_nor_evaluator() -> None:
    imported = _imports(ACQUISITION)
    assert not any("parser" in name for name in imported)
    assert not any("evaluator" in name for name in imported)
    source = _executable(ACQUISITION)
    for forbidden in ("parse_payload", "evaluate(", "ParsedPage", "TestResult", "decode("):
        assert forbidden not in source


def test_the_acquisition_composition_imports_no_read_surface_or_report() -> None:
    imported = _imports(ACQUISITION)
    assert not any(name.endswith(".read") for name in imported)
    assert not any(name.endswith(".report") for name in imported)
    source = _executable(ACQUISITION)
    # ``.get_object(`` is the call; ``get_object_count=0`` is the field asserting the
    # call never happened, and forbidding the counter would forbid the evidence.
    for forbidden in (".get_object(", "LicensedObjectReader", "read_exact", "publish_report"):
        assert forbidden not in source


def test_the_acquisition_path_names_no_listing_delete_or_control_operation() -> None:
    source = _executable(ACQUISITION)
    for forbidden in ("list_objects", "delete_object", "copy_object", "CONTROL"):
        assert forbidden not in source


# -- the assessment path cannot reach a credential or a provider --------------


def test_the_assessment_composition_imports_no_credential_or_secrets_boundary() -> None:
    imported = _imports(ASSESSMENT)
    assert not any("secrets" in name for name in imported)
    assert not any("credentials" in name for name in imported)
    source = _executable(ASSESSMENT)
    for forbidden in (
        "SharadarCredential",
        "get_secret_value",
        "sharadar_credential_from_secret",
        "is_usable_secret_identifier",
    ):
        assert forbidden not in source


def test_the_assessment_composition_imports_no_provider_transport_or_client() -> None:
    imported = _imports(ASSESSMENT)
    assert not any("transport" in name for name in imported)
    assert not any(name.endswith("sharadar.client") for name in imported)
    source = _executable(ASSESSMENT)
    for forbidden in ("SharadarClient", "UrllibTransport", "fetch(", "api_key"):
        assert forbidden not in source


def test_the_assessment_composition_publishes_no_bronze_object() -> None:
    source = _executable(ASSESSMENT)
    for forbidden in ("publish_bronze_payload", "publish_sharadar_payload", "put_if_absent"):
        assert forbidden not in source


def test_neither_composition_names_a_listing_operation() -> None:
    for path in (ACQUISITION, ASSESSMENT):
        assert "list_objects" not in _executable(path)


# -- no SDK client is constructed anywhere under src/ -------------------------


ALL_SRC_MODULES = sorted(SRC.rglob("*.py"))


@pytest.mark.parametrize("path", ALL_SRC_MODULES, ids=lambda path: path.name)
def test_no_module_under_src_imports_the_aws_sdk(path: Path) -> None:
    imported = _imports(path)
    assert "boto3" not in imported
    assert "botocore" not in imported


@pytest.mark.parametrize("path", QUALIFY_MODULES, ids=lambda path: path.name)
def test_no_qualification_module_constructs_an_sdk_client(path: Path) -> None:
    source = _executable(path)
    for forbidden in ("boto3", "botocore", "Session(", 'client("s3"', "client('s3'"):
        assert forbidden not in source


@pytest.mark.parametrize("path", QUALIFY_MODULES, ids=lambda path: path.name)
def test_no_qualification_module_has_an_entry_point_or_reads_the_environment(
    path: Path,
) -> None:
    source = _executable(path)
    for forbidden in ('__name__ == "__main__"', "argparse", "sys.argv", "os.environ"):
        assert forbidden not in source


@pytest.mark.parametrize("path", QUALIFY_MODULES, ids=lambda path: path.name)
def test_no_qualification_module_writes_a_local_file(path: Path) -> None:
    source = _executable(path)
    for forbidden in ("write_text", "write_bytes", "mkdir", "tempfile"):
        assert forbidden not in source


def test_only_the_inventory_module_reads_a_file_and_only_the_private_one() -> None:
    readers = [
        path
        for path in QUALIFY_MODULES
        if "read_bytes" in _executable(path) or "read_text" in _executable(path)
    ]
    assert [path.name for path in readers] == ["inventory.py"]


# -- exactly one construction site for the licensed store ---------------------


def test_exactly_one_qualification_module_constructs_the_licensed_store() -> None:
    constructors = [
        path.name for path in QUALIFY_MODULES if "S3ResearchObjectStore(" in _source(path)
    ]
    assert constructors == ["acquisition.py"]


def test_the_earlier_composition_root_remains_the_ingestion_path_s_only_one() -> None:
    # The accepted single-constructor guard is scoped to the ingestion package, and
    # this slice does not widen it: the new construction lives in a different package
    # under its own governance.
    constructors = [
        path.name
        for path in sorted((INGEST / "sharadar").glob("*.py"))
        if "S3ResearchObjectStore(" in _source(path)
    ]
    assert constructors == ["composition.py"]


def test_no_qualification_module_constructs_the_assessment_reader() -> None:
    # Constructed only at the operator boundary, never inside the package. The
    # reader's own ``__repr__`` names its class, which is not a construction -- so the
    # scan is over calls in the parsed tree rather than over a substring.
    for path in QUALIFY_MODULES:
        for node in ast.walk(ast.parse(_source(path))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != "LicensedObjectReader"


# -- public-pit is not expressible anywhere in the package --------------------


@pytest.mark.parametrize("path", QUALIFY_MODULES, ids=lambda path: path.name)
def test_public_pit_is_not_expressible_in_the_qualification_package(path: Path) -> None:
    # Over the executable source: a comment explaining why the value is unreachable
    # is not a way of producing it, and forbidding the explanation would only make
    # the next reader delete the explanation.
    assert "PUBLIC_PIT" not in _executable(path)


@pytest.mark.parametrize("path", QUALIFY_MODULES, ids=lambda path: path.name)
def test_no_fourth_acquisition_mode_is_introduced(path: Path) -> None:
    # The production modes, named as modes. A bare "UPDATE" substring also matches
    # ``lastupdated``, which is a vendor column name and not an acquisition mode.
    source = _executable(path)
    for forbidden in (
        "AcquisitionMode.BACKFILL",
        "AcquisitionMode.UPDATE",
        "'BACKFILL'",
        '"BACKFILL"',
    ):
        assert forbidden not in source


# -- the two entry points are new and separate --------------------------------


def test_exactly_two_new_entry_points_exist() -> None:
    assert (SCRIPTS / "sharadar_empirical_qualification.py").is_file()
    assert (SCRIPTS / "sharadar_qualification_assessment.py").is_file()


def test_neither_new_entry_point_imports_the_other() -> None:
    acquire = SCRIPTS / "sharadar_empirical_qualification.py"
    assess = SCRIPTS / "sharadar_qualification_assessment.py"
    assert "sharadar_qualification_assessment" not in _source(acquire)
    assert "sharadar_empirical_qualification" not in _source(assess)


def test_the_earlier_operator_surfaces_are_unchanged_by_this_slice() -> None:
    for name in (
        "sharadar_authenticated_qualification.py",
        "sharadar_binding_preflight.py",
        "sharadar_plan_check.py",
        "sharadar_private_qualification.py",
    ):
        source = _source(SCRIPTS / name)
        assert "data.qualify" not in source
        assert "sharadar_empirical_qualification" not in source
        assert "sharadar_qualification_assessment" not in source


def test_the_installed_package_re_exports_neither_entry_point() -> None:
    for path in SRC.rglob("__init__.py"):
        source = _source(path)
        assert "sharadar_empirical_qualification" not in source
        assert "sharadar_qualification_assessment" not in source
