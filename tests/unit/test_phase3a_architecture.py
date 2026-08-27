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
        "storage.py",
        "contracts",
        "curate",
        "ingest",
        "live",
        "normalize",
        "pit",
        "quality",
    }
    present = {entry.name for entry in DATA_ROOT.iterdir() if entry.name != "__pycache__"}
    assert present == authorized, (
        f"kalpamani.data holds exactly the authorized A1 surface. Unexpected: "
        f"{sorted(present - authorized)}; missing: {sorted(authorized - present)}"
    )


#: SDKs and data engines this slice must not depend on. The check is about what
#: the project declares and imports, never about what happens to be installed in
#: whichever virtualenv the suite runs in.
FORBIDDEN_DISTRIBUTIONS = (
    "duckdb",
    "pyarrow",
    "pandas",
    "polars",
    "boto3",
    "botocore",
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


def test_the_project_still_declares_no_runtime_dependencies() -> None:
    """The A1 kernel adds none. A data engine is a decision gate G1 has not reached."""
    content = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "dependencies = []" in content


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
