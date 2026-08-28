"""Guards that keep the bootstrap phase inside its authorized scope.

These tests fail if a future change smuggles brokerage connectivity, strategy
logic or a credential into the repository before the corresponding phase is
explicitly approved.
"""

from __future__ import annotations

import importlib
import pkgutil
import re
from pathlib import Path

import pytest

import kalpamani

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = PROJECT_ROOT / "src" / "kalpamani"

#: Packages that must contain no implementation modules during bootstrap.
#:
#: ``data`` left this list when the Phase-3A A1 foundation kernel was authorized.
#: It is not unguarded: ``test_phase3a_architecture.py`` asserts that
#: ``kalpamani.data`` holds exactly the authorized A1 surface and nothing wider,
#: which is a tighter constraint than "empty" was -- it names what may be there
#: rather than only forbidding everything.
EMPTY_BY_DESIGN = (
    "risk",
    "portfolio",
    "research",
    "monitoring",
    "strategies/breakout",
    "strategies/pullback",
    "strategies/pead",
)

#: Phase 2 permits exactly two modules under broker/: the Phase 1 read-only
#: account boundary (ADR-0002) and the minimum order-capable boundary
#: (ADR-0004). Anything else there needs a new ADR.
BROKER_ALLOWED_MODULES = ["account.py", "orders.py"]

#: Phase 2 permits exactly these modules under execution/, per ADR-0004.
#: Widening the execution surface is an ADR-level change.
EXECUTION_ALLOWED_MODULES = [
    "coordinator.py",
    "cycle.py",
    "envelope.py",
    "halt.py",
    "identity.py",
    "lifecycle.py",
    "reconciliation.py",
    "session.py",
    "state_store.py",
    "trading_window.py",
]

#: Import names of brokerage/engine clients that must not be reachable yet.
FORBIDDEN_IMPORTS = ("ib_insync", "ibapi", "ib_async", "QuantConnect", "AlgorithmImports")


@pytest.mark.parametrize("relative_package", EMPTY_BY_DESIGN)
def test_package_contains_no_implementation_yet(relative_package: str) -> None:
    """Only __init__.py may exist in a package that is empty by design."""
    package_dir = PACKAGE_ROOT / relative_package
    assert package_dir.is_dir(), f"Expected package directory {package_dir} to exist."

    modules = sorted(p.name for p in package_dir.glob("*.py") if p.name != "__init__.py")
    assert modules == [], (
        f"kalpamani/{relative_package} must stay empty during bootstrap, found: {modules}. "
        "Implementing it requires explicit phase approval."
    )


def test_broker_package_contains_only_the_readonly_boundary() -> None:
    """ADR-0002 permits the read-only boundary; ADR-0004 adds the order boundary."""
    package_dir = PACKAGE_ROOT / "broker"
    modules = sorted(p.name for p in package_dir.glob("*.py") if p.name != "__init__.py")
    assert modules == BROKER_ALLOWED_MODULES, (
        f"kalpamani/broker must contain only {BROKER_ALLOWED_MODULES} during Phase 2, "
        f"found: {modules}. Extending the brokerage surface requires a new ADR."
    )


def test_execution_package_contains_only_the_phase2_boundary() -> None:
    """ADR-0004 authorises this execution surface and no more."""
    package_dir = PACKAGE_ROOT / "execution"
    modules = sorted(p.name for p in package_dir.glob("*.py") if p.name != "__init__.py")
    assert modules == EXECUTION_ALLOWED_MODULES, (
        f"kalpamani/execution must contain only {EXECUTION_ALLOWED_MODULES} during Phase 2, "
        f"found: {modules}. Widening the execution surface requires a new ADR."
    )


def test_no_brokerage_client_is_importable() -> None:
    """No IBKR or LEAN client library may be an installed dependency yet."""
    for module_name in FORBIDDEN_IMPORTS:
        with pytest.raises(ImportError):
            importlib.import_module(module_name)


#: The project's entire runtime dependency list, as ADR-0011 authorized it.
#: Written out rather than pattern-matched: a guard that accepted "anything
#: starting with boto3" would accept a second entry beside it.
AUTHORIZED_RUNTIME_DEPENDENCIES = ["boto3>=1.36.0,<2.0"]


def declared_runtime_dependencies() -> list[str]:
    """The `[project] dependencies` array, and nothing from the dev extras."""
    content = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"^dependencies = \[(.*?)^\]", content, flags=re.M | re.S)
    assert block is not None, "pyproject declares no runtime dependency array at all"
    return re.findall(r'"([^"]+)"', block.group(1))


def test_package_declares_only_the_authorized_runtime_dependency() -> None:
    """The bootstrap list was empty until 2026-08-28; now it holds exactly one entry.

    ADR-0011 gave up the zero-dependency posture for the AWS SDK alone, and the
    guard is narrowed to match rather than deleted. The point it protected is
    unchanged: no brokerage, market-data or AI client library may arrive
    unannounced, and each of those is still refused by name above.
    """
    assert declared_runtime_dependencies() == AUTHORIZED_RUNTIME_DEPENDENCIES


def test_env_example_contains_no_real_credentials() -> None:
    """.env.example must hold placeholders only."""
    content = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        _, _, value = stripped.partition("=")
        value = value.strip()
        if not value:
            continue
        is_placeholder = value.startswith("<") and value.endswith(">")
        is_safe_default = value in {
            "research",
            "local-dev",
            "80000",
            "127.0.0.1",
            "7497",
            "1",
            "DU0000000",
            "localhost",
            "5432",
            "kalpamani",
            "anthropic",
            "claude-opus-5",
            "INFO",
            "<tbd>",
        }
        assert is_placeholder or is_safe_default, (
            f".env.example line {stripped!r} looks like a real value. "
            "It must contain variable names and placeholders only."
        )


def test_all_declared_packages_import_cleanly() -> None:
    """Every kalpamani subpackage must import without side effects."""
    for module in pkgutil.walk_packages(kalpamani.__path__, prefix="kalpamani."):
        importlib.import_module(module.name)


def test_gitignore_excludes_secret_files() -> None:
    content = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    for required in (".env", "!.env.example", "*.pem", "*.key", "secrets/", "lean/data/"):
        assert required in content, f".gitignore must exclude {required!r}."
