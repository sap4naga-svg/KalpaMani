"""Static architecture boundaries, enforced by test rather than by convention.

ADR-0004 s.10 established the pattern for the execution boundary: a rule nobody
can accidentally break is worth more than a rule everyone agrees with. The same
shape applies here.

These are **AST scans**, not text searches. A text search over source would trip
on the word "current" in a docstring and miss an aliased import; the parser sees
what the interpreter sees.
"""

from __future__ import annotations

import ast
import inspect
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from kalpamani.data.pit.accessors import PointInTimeReader

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = PROJECT_ROOT / "src" / "kalpamani"
DATA_ROOT = PACKAGE_ROOT / "data"

#: Packages that may later import ``data.pit`` and ``data.contracts`` and nothing
#: else from the data platform. They are empty today, which is exactly when a
#: boundary is cheapest to establish.
CONSUMER_PACKAGES = ("strategies", "risk", "portfolio", "research")

#: What a consumer package may never import from the data platform.
CONSUMER_FORBIDDEN = (
    "kalpamani.data.live",
    "kalpamani.data.ingest",
    "kalpamani.data.normalize",
    "kalpamani.data.curate",
    "kalpamani.data.storage",
)

#: Identifiers that would smuggle a non-point-in-time route into research paths.
FORBIDDEN_IDENTIFIERS = frozenset({"latest", "current", "most_recent", "today"})


def _python_files(root: Path) -> Iterator[Path]:
    yield from sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _module_name(path: Path) -> str:
    """The dotted module name a file would be imported as."""
    relative = path.relative_to(PACKAGE_ROOT.parent).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _package_name(path: Path) -> str:
    """The package a relative import inside ``path`` resolves against."""
    module = _module_name(path)
    if path.name == "__init__.py":
        return module
    return module.rpartition(".")[0]


def imported_modules(source: str, *, module_package: str, filename: str = "<memory>") -> set[str]:
    """Every module a source file imports, absolute and relative alike.

    Resolves three shapes a naive scan misses, each of which would let a
    forbidden dependency in unnoticed:

    - ``import a.b as c`` -- the **bound name** is ``c``, but the imported module
      is still ``a.b``, and that is what the boundary is about;
    - ``from ..data import live`` -- a relative import at any level, resolved
      against the importing file's own package;
    - ``from a.b import c`` -- both ``a.b`` and ``a.b.c`` count, because ``c`` may
      be a submodule rather than a name.
    """
    tree = ast.parse(source, filename=filename)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module or ""
            else:
                anchor = module_package.split(".")
                trimmed = anchor[: len(anchor) - (node.level - 1)] if node.level > 1 else anchor
                base = ".".join([*trimmed, node.module] if node.module else trimmed)
            if not base:
                continue
            modules.add(base)
            modules.update(f"{base}.{alias.name}" for alias in node.names)
    return modules


def _imported_modules(path: Path) -> set[str]:
    return imported_modules(
        path.read_text(encoding="utf-8"),
        module_package=_package_name(path),
        filename=str(path),
    )


def _identifiers(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.keyword) and node.arg:
            names.add(node.arg)
    return names


# ---------------------------------------------------------------------------
# 27 -- the data platform and the brokerage boundary do not meet
# ---------------------------------------------------------------------------


def test_no_data_module_imports_the_broker_or_execution_packages() -> None:
    """The data platform has no brokerage boundary to breach (ADR-0002 s.13)."""
    offenders: list[str] = []
    for path in _python_files(DATA_ROOT):
        for module in _imported_modules(path):
            if module.startswith(("kalpamani.broker", "kalpamani.execution")):
                offenders.append(f"{path.relative_to(PROJECT_ROOT)} imports {module}")
    assert offenders == [], (
        f"kalpamani.data must not reach the brokerage or execution boundary. Found: {offenders}"
    )


def test_no_broker_identifier_appears_in_any_data_contract() -> None:
    """No brokerage account id, binding digest or broker order id (CLAUDE.md s.3)."""
    forbidden = ("BrokerId", "broker_id", "account_binding", "account_id", "perm_id", "PermId")
    offenders: list[str] = []
    for path in _python_files(DATA_ROOT):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                offenders.append(f"{path.relative_to(PROJECT_ROOT)} mentions {token!r}")
    assert offenders == [], (
        "The data platform and the brokerage boundary do not meet, so a broker-native "
        f"identifier has no reason to appear here. Found: {offenders}"
    )


# ---------------------------------------------------------------------------
# 28 -- research paths cannot reach data.live or the build layers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("package", CONSUMER_PACKAGES)
def test_a_consumer_package_imports_only_pit_and_contracts(package: str) -> None:
    """Two packages, not one package with a flag.

    A flag is a thing that can be set wrongly; a missing import is a thing that
    fails in CI.
    """
    root = PACKAGE_ROOT / package
    offenders: list[str] = []
    for path in _python_files(root):
        for module in _imported_modules(path):
            if any(module.startswith(bad) for bad in CONSUMER_FORBIDDEN):
                offenders.append(f"{path.relative_to(PROJECT_ROOT)} imports {module}")
    assert offenders == [], (
        f"{package} may import kalpamani.data.pit and kalpamani.data.contracts and nothing "
        f"else from the data platform. Found: {offenders}"
    )


def test_the_pit_package_does_not_import_the_live_package() -> None:
    """Historical and current access do not meet, even inside the data platform."""
    for path in _python_files(DATA_ROOT / "pit"):
        assert not any(
            module.startswith("kalpamani.data.live") for module in _imported_modules(path)
        ), f"{path.relative_to(PROJECT_ROOT)} imports kalpamani.data.live"


def test_the_live_package_is_deliberately_unimplemented() -> None:
    modules = sorted(p.name for p in (DATA_ROOT / "live").glob("*.py") if p.name != "__init__.py")
    assert modules == [], (
        "data.live carries no accessor in this slice. Adding one is a phase decision, not an "
        f"implementation detail. Found: {modules}"
    )


def test_the_contracts_package_performs_no_io() -> None:
    """Contracts hold schemas and rules. A schema that opens a file is not a schema."""
    forbidden = {"pathlib", "os", "io", "socket", "urllib", "urllib.request", "http.client"}
    offenders: list[str] = []
    for path in _python_files(DATA_ROOT / "contracts"):
        for module in _imported_modules(path):
            if module.split(".")[0] in {name.split(".")[0] for name in forbidden}:
                offenders.append(f"{path.relative_to(PROJECT_ROOT)} imports {module}")
    assert offenders == [], f"kalpamani.data.contracts must stay pure. Found: {offenders}"


# ---------------------------------------------------------------------------
# 29 -- accessor parameters have no defaults
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "accessor",
    [
        PointInTimeReader.get_security_universe,
        PointInTimeReader.get_price_history,
        PointInTimeReader.get_classification,
    ],
)
def test_every_historical_accessor_parameter_is_required_and_keyword_only(
    accessor: object,
) -> None:
    """A default here answers the question on the caller's behalf, silently."""
    signature = inspect.signature(accessor)  # type: ignore[arg-type]
    for name, parameter in signature.parameters.items():
        if name == "self":
            continue
        assert parameter.default is inspect.Parameter.empty, (
            f"{accessor.__qualname__}({name}=...) carries a default. as_of, profile, "  # type: ignore[attr-defined]
            "revision_view and adjustment_mode are decisions for whoever asks the question."
        )
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, (
            f"{accessor.__qualname__}({name}) must be keyword-only, so a positional "  # type: ignore[attr-defined]
            "call cannot transpose two arguments of the same type."
        )


def test_as_of_and_profile_are_structurally_mandatory() -> None:
    """Omitting one is a TypeError at the call site, not a quiet fallback."""
    for accessor in (
        PointInTimeReader.get_security_universe,
        PointInTimeReader.get_price_history,
        PointInTimeReader.get_classification,
    ):
        parameters = inspect.signature(accessor).parameters
        assert "as_of" in parameters
        assert "profile" in parameters


def test_the_price_accessor_requires_an_explicit_adjustment_mode() -> None:
    parameters = inspect.signature(PointInTimeReader.get_price_history).parameters
    assert "adjustment_mode" in parameters
    assert parameters["adjustment_mode"].default is inspect.Parameter.empty


# ---------------------------------------------------------------------------
# 30 -- no latest/current/today route
# ---------------------------------------------------------------------------


def test_no_latest_or_current_identifier_exists_in_the_pit_package() -> None:
    offenders: list[str] = []
    for path in _python_files(DATA_ROOT / "pit"):
        hits = _identifiers(path) & FORBIDDEN_IDENTIFIERS
        if hits:
            offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {sorted(hits)}")
    assert offenders == [], (
        "There is no latest/current/today convenience route in historical access. "
        f"Found: {offenders}"
    )


@pytest.mark.parametrize("package", CONSUMER_PACKAGES)
def test_no_consumer_package_names_a_non_point_in_time_route(package: str) -> None:
    offenders: list[str] = []
    for path in _python_files(PACKAGE_ROOT / package):
        identifiers = _identifiers(path)
        hits = identifiers & FORBIDDEN_IDENTIFIERS
        if hits:
            offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {sorted(hits)}")
        if "LATEST_RESTATED" in identifiers:
            offenders.append(f"{path.relative_to(PROJECT_ROOT)}: LATEST_RESTATED")
    assert offenders == [], f"{package} may not reach a non-point-in-time route. Found: {offenders}"


def test_latest_restated_is_refused_at_runtime_as_well_as_statically() -> None:
    """The two enforcements must agree, or one of them is decoration."""
    from fixtures import phase3a
    from kalpamani.data.contracts.errors import NonPointInTimeViewError
    from kalpamani.data.contracts.vocabulary import InformationSetProfile, RevisionView
    from kalpamani.data.pit.accessors import select_revision

    with pytest.raises(NonPointInTimeViewError, match="not a point-in-time view"):
        select_revision(
            phase3a.listings(),
            revision_view=RevisionView.LATEST_RESTATED,
            as_of=phase3a.utc(2026, 1, 1),
            resolved_profile=InformationSetProfile.PUBLIC_PIT,
            approvals=phase3a.approvals(),
        )


def test_the_revision_view_is_required_and_has_no_default() -> None:
    from kalpamani.data.pit.accessors import select_revision

    parameters = inspect.signature(select_revision).parameters
    assert parameters["revision_view"].default is inspect.Parameter.empty
    assert parameters["revision_view"].kind is inspect.Parameter.KEYWORD_ONLY


# ---------------------------------------------------------------------------
# Package scope
# ---------------------------------------------------------------------------


def test_the_data_package_holds_only_the_authorized_a1_surface() -> None:
    """Widening the data platform beyond the A1 slice is a phase decision."""
    authorized = {
        "__init__.py",
        "objectstore.py",
        "contracts",
        "curate",
        "ingest",
        "live",
        "normalize",
        "pit",
        "quality",
        # The private empirical qualification package. Deliberately **not** under
        # `ingest`, so the acquisition path stays parser-free and the separation is
        # a property of the import graph rather than a rule somebody remembers.
        "qualify",
        "storage",
    }
    present = {entry.name for entry in DATA_ROOT.iterdir() if entry.name != "__pycache__"}
    assert present == authorized, (
        f"kalpamani.data holds exactly the authorized A1 surface. Unexpected: "
        f"{sorted(present - authorized)}; missing: {sorted(authorized - present)}"
    )


#: SDKs and data engines this project must not depend on. The check is about what
#: the project declares and imports, never about what happens to be installed in
#: whichever virtualenv the suite runs in.
#:
#: **`boto3` and `botocore` left this list on 2026-08-28** (ADR-0011), and the
#: replacement rule is narrower rather than absent: the AWS SDK is declared as the
#: single runtime dependency, and `AWS_SDK_BOUNDARY` below is the only module
#: permitted to name it. Everything else here is still forbidden everywhere.
FORBIDDEN_DISTRIBUTIONS = (
    "duckdb",
    "pyarrow",
    "pandas",
    "polars",
    "moto",
    "localstack",
    "requests",
    "httpx",
    "urllib3",
    "psycopg",
    "psycopg2",
    "sqlalchemy",
    "ibapi",
    "ib_insync",
    "ib_async",
)


def _declared_dependencies() -> list[str]:
    """Every distribution the project declares, runtime and dev alike."""
    content = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    declared: list[str] = []
    for match in re.finditer(r"^\s*\"([^\"]+)\",?\s*$", content, flags=re.M):
        declared.append(match.group(1))
    return declared


def test_the_storage_package_holds_only_the_authorized_backends() -> None:
    """Two backends, named. A third would be a decision, not a file."""
    present = {
        entry.name for entry in (DATA_ROOT / "storage").iterdir() if entry.name != "__pycache__"
    }
    assert present == {"__init__.py", "local.py", "s3.py"}, sorted(present)


def test_importing_the_storage_package_does_not_pull_in_the_s3_backend() -> None:
    """``kalpamani.data.storage`` re-exports the local store only.

    A convenience re-export of ``s3`` would make every importer of the local
    table store transitively depend on the AWS boundary, which is the coupling
    the package split exists to prevent. Reaching the S3 store is deliberately an
    explicit ``from kalpamani.data.storage.s3 import ...``.

    Proven in a **fresh interpreter** rather than against this one: by the time
    this test runs, some earlier test has almost certainly imported the S3
    module, so ``sys.modules`` here would say nothing at all.
    """
    probe = (
        "import sys;"
        "import kalpamani.data.storage as pkg;"
        "print(pkg.LocalTableStore.__name__,"
        " 'kalpamani.data.storage.s3' in sys.modules,"
        " any(m.split('.')[0] in ('boto3', 'botocore') for m in sys.modules))"
    )
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
        cwd=PROJECT_ROOT,
    )
    assert completed.stdout.split() == ["LocalTableStore", "False", "False"], completed.stdout


#: The one module allowed to speak AWS. Everything above it depends on the
#: `ResearchObjectStore` protocol and knows no bucket, ARN, account or SDK type.
AWS_SDK_BOUNDARY = DATA_ROOT / "storage" / "s3.py"

#: Distributions that only `AWS_SDK_BOUNDARY` may import.
AWS_SDK_DISTRIBUTIONS = ("boto3", "botocore")


def test_only_the_storage_boundary_may_import_the_aws_sdk() -> None:
    """A narrower rule than "nobody", and it has to be enforced rather than agreed.

    ADR-0011 authorized one S3 adapter. If the SDK could be imported anywhere,
    the seam that keeps buckets and credentials out of the provider packages and
    the point-in-time kernel would be a convention rather than a boundary.
    """
    offenders: list[str] = []
    for path in _python_files(PACKAGE_ROOT):
        if path == AWS_SDK_BOUNDARY:
            continue
        for module in _imported_modules(path):
            if module.split(".")[0] in AWS_SDK_DISTRIBUTIONS:
                offenders.append(f"{path.relative_to(PROJECT_ROOT)} imports {module}")
    assert offenders == [], f"only data/storage/s3.py may name the AWS SDK. Found: {offenders}"


def test_the_s3_adapter_imports_no_sdk_at_all() -> None:
    """Stronger than the boundary rule, and worth stating separately.

    The client is injected, so even the one permitted module does not import the
    SDK today: importing the data platform pulls in no AWS code, opens no socket
    and performs no ambient credential discovery. If a future edit needs the
    import, the boundary test above still allows it -- here.
    """
    assert AWS_SDK_BOUNDARY.is_file()
    imported = _imported_modules(AWS_SDK_BOUNDARY)
    assert not {module.split(".")[0] for module in imported} & set(AWS_SDK_DISTRIBUTIONS)


#: The one module ADR-0014 authorized to construct the licensed store.
#:
#: Named as a single path rather than a directory: a second composition module
#: appearing beside it has to pass review rather than merely be in the right
#: folder.
COMPOSITION_ROOT = (
    PROJECT_ROOT / "src" / "kalpamani" / "data" / "ingest" / "sharadar" / "composition.py"
)

#: The empirical qualification package's own composition.
#:
#: It **used to** construct the shared licensed store and no longer does: ADR-0019
#: made the acquisition path write-only, and the shared store resolves a ``412``
#: with a ``HeadObject`` that AWS maps onto ``s3:GetObject``. It now composes the
#: package's own write-only publisher instead, so the permission list below goes
#: back to one module -- a **narrowing**, not a relaxation.
EMPIRICAL_COMPOSITION = (
    PROJECT_ROOT / "src" / "kalpamani" / "data" / "qualify" / "sharadar" / "acquisition.py"
)

#: Every module permitted to construct the licensed store, and nothing else.
#:
#: One again, as it was before the empirical package existed. A *second* module
#: constructing a licensed store fails here, which is the property this guard exists
#: for and which a count would not have preserved.
STORE_BUILDERS = (COMPOSITION_ROOT,)

#: SDK construction, which ADR-0014 did **not** authorize anywhere.
#:
#: Kept separate from the store because the two are different decisions. A store
#: bound to an injected client sends nothing until someone hands it a real one;
#: a `boto3` session or client *is* the real one, and building it here would be
#: ambient credential resolution inside the data platform.
SDK_CONSTRUCTIONS = frozenset({"client", "resource", "Session"})


def test_no_data_module_constructs_an_s3_client_or_store() -> None:
    """One composition root exists, and nothing else may build the shared store.

    ADR-0014 narrowed this rule; it did not remove it. The earlier rule was "no
    composition root exists", which was correct while none was authorized, and it
    then became "exactly one". The empirical qualification package briefly made it
    two, and ADR-0019 took it back to one: that package's acquisition path is
    write-only now and builds its own publisher, so a **second** module constructing
    the shared licensed store fails here.

    **SDK construction is still forbidden everywhere, including the composition
    root.** The S3 client is injected there too, so the data platform still
    imports no SDK, opens no socket and performs no ambient credential
    discovery.
    """
    offenders: list[str] = []
    for path in _python_files(PACKAGE_ROOT):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        authorized = path in STORE_BUILDERS
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else ""
            )
            if name in SDK_CONSTRUCTIONS:
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno} {name}")
            elif name == "S3ResearchObjectStore" and not authorized:
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno} {name}")
    assert offenders == [], (
        f"no runner or second composition root is authorized. Found: {offenders}"
    )


def test_the_empirical_acquisition_never_constructs_the_shared_licensed_store() -> None:
    """The replacement assertion for the permission this correction removed.

    Narrowing ``STORE_BUILDERS`` back to one module says the shared store is built
    in one place. It does not, on its own, say *which* place stopped building it --
    so this names the module ADR-0019 made write-only and asserts the construction
    is gone, by parse rather than by substring. A future edit that reinstated it
    would fail here as well as in the count above.
    """
    tree = ast.parse(EMPIRICAL_COMPOSITION.read_text(encoding="utf-8"))
    assert not [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "S3ResearchObjectStore"
    ], "the write-only acquisition path must not construct the shared licensed store"
    assert "S3ResearchObjectStore" not in {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }, "the write-only acquisition path must not import the shared licensed store"


def test_only_the_authorized_module_constructs_the_licensed_store() -> None:
    """The permission is a named module, not a count that could drift."""
    builders = [
        path.relative_to(PROJECT_ROOT)
        for path in _python_files(PACKAGE_ROOT)
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "S3ResearchObjectStore"
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        )
    ]
    assert sorted(builders) == sorted(path.relative_to(PROJECT_ROOT) for path in STORE_BUILDERS), (
        f"the licensed store is constructed at: {builders}"
    )


def _executable_code(path: Path) -> str:
    """The module's code with every docstring removed.

    A guard that scanned raw source would fire on the prose explaining what the
    module refuses to do -- which would either weaken the guard or forbid saying
    why it exists. Unparsing a docstring-stripped tree keeps string literals and
    attribute access, and drops only the narration.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        first = node.body[0] if node.body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            node.body = node.body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def test_the_s3_client_protocol_declares_exactly_two_operations() -> None:
    """The injected client is typed by what the store may ask of it.

    A wider protocol would let a future edit reach a destructive operation with
    no type error, and would oblige every synthetic client to implement one.
    """
    members = {
        node.name
        for node in ast.walk(ast.parse(AWS_SDK_BOUNDARY.read_text(encoding="utf-8")))
        if isinstance(node, ast.ClassDef) and node.name == "S3Client"
        for node in node.body
        if isinstance(node, ast.FunctionDef)
    }
    assert members == {"put_object", "head_object"}, sorted(members)


def test_the_s3_store_adds_nothing_to_the_protocol_surface() -> None:
    """Deletion belongs to the separately roled path under ADR-0007. A routine
    research writer must never receive it, and must not grow a read or list
    surface either."""
    source = _executable_code(AWS_SDK_BOUNDARY)
    for forbidden in (
        "delete_object",
        "delete_objects",
        "list_objects",
        "list_objects_v2",
        "get_object",
        "copy_object",
        "upload_file",
        "S3Transfer",
        "create_multipart_upload",
        "put_object_acl",
        "put_bucket_versioning",
    ):
        assert forbidden not in source, f"{forbidden} has no place in a research writer"


def test_the_project_declares_only_the_aws_sdk_at_runtime() -> None:
    """One dependency, bounded, and named. The zero-dependency posture was given
    up deliberately by ADR-0011 rather than drifting."""
    content = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    declared = re.search(r"^dependencies = \[(.*?)^\]", content, flags=re.M | re.S)
    assert declared is not None
    body = declared.group(1)
    entries = re.findall(r'"([^"]+)"', body)
    assert entries == ["boto3>=1.36.0,<2.0"], entries


def test_no_vendor_sdk_or_data_engine_is_declared_as_a_dependency() -> None:
    """A dependency the project does not declare cannot be relied on.

    Deliberately **not** "importing X must fail". That would make the result
    depend on what unrelated tooling happens to be installed in the developer's
    virtualenv -- passing on a clean machine and failing on one where someone
    installed pandas for something else, while saying nothing about KalpaMani.
    """
    declared = " ".join(_declared_dependencies()).lower()
    offenders = [name for name in FORBIDDEN_DISTRIBUTIONS if re.search(rf"\b{name}\b", declared)]
    assert offenders == [], (
        f"pyproject declares {offenders}. No vendor SDK, cloud SDK, database driver or data "
        "engine is authorized in this slice."
    )


def test_no_kalpamani_module_imports_a_vendor_sdk_or_data_engine() -> None:
    """The other half: declared or not, the source must not reach for one."""
    offenders: list[str] = []
    for path in _python_files(PACKAGE_ROOT):
        for module in _imported_modules(path):
            root = module.split(".")[0]
            if root in FORBIDDEN_DISTRIBUTIONS:
                offenders.append(f"{path.relative_to(PROJECT_ROOT)} imports {module}")
    assert offenders == [], f"Found: {offenders}"


def test_no_service_emulator_is_introduced() -> None:
    """Moto and LocalStack are emulators, not evidence.

    A synthetic in-process client proves what the adapter *sends* and what it
    refuses to guess at, which is the part that has to be right. An emulator
    would add a large dependency and a second implementation of S3's semantics
    to be wrong about.
    """
    content = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    for emulator in ("moto", "localstack", "minio"):
        assert emulator not in content


# ---------------------------------------------------------------------------
# The scanner's own proof
# ---------------------------------------------------------------------------


def test_the_import_scanner_resolves_a_forbidden_relative_import() -> None:
    """A boundary check that cannot see a relative import is decoration.

    The fixture is source text rather than a file on disk, so the guard is proven
    against a violation that must never actually exist in the tree.
    """
    # A file at kalpamani/strategies/foo.py: one level up from its own package.
    modules = imported_modules(
        "from ..data.live import something\n", module_package="kalpamani.strategies"
    )
    assert "kalpamani.data.live" in modules
    assert any(module.startswith(bad) for module in modules for bad in CONSUMER_FORBIDDEN)

    # And a level deeper, from kalpamani/strategies/breakout/foo.py.
    deeper = imported_modules(
        "from ...data.live import something\n", module_package="kalpamani.strategies.breakout"
    )
    assert "kalpamani.data.live" in deeper


def test_the_import_scanner_resolves_a_single_level_relative_import() -> None:
    source = "from .curate import publication\n"
    modules = imported_modules(source, module_package="kalpamani.data")
    assert "kalpamani.data.curate" in modules
    assert "kalpamani.data.curate.publication" in modules


def test_the_import_scanner_sees_through_an_alias() -> None:
    """The bound name is not the imported module, and the boundary is about the module."""
    source = "import kalpamani.data.live as anything\n"
    modules = imported_modules(source, module_package="kalpamani.research")
    assert "kalpamani.data.live" in modules

    source = "from kalpamani.data import live as elsewhere\n"
    modules = imported_modules(source, module_package="kalpamani.research")
    assert "kalpamani.data.live" in modules


def test_the_import_scanner_does_not_invent_violations() -> None:
    """NEGATIVE CONTROL. A permitted import must not trip the guard."""
    source = "from kalpamani.data.pit import accessors\nfrom kalpamani.data import contracts\n"
    modules = imported_modules(source, module_package="kalpamani.research")
    assert not any(module.startswith(bad) for module in modules for bad in CONSUMER_FORBIDDEN)
