"""The offline equity Brain stays inside its authorization, checked against the code.

This cycle narrows the earlier "Brain runtime NOT AUTHORIZED" restriction to authorize an
**offline** equity Brain on **synthetic** inputs, with ``CandidateIntent`` as its only
output. These guards are the boundary of that authorization, expressed over the source
tree so a later change that oversteps it fails here rather than in review:

* the Brain reaches no network, provider, broker, model, database or cloud SDK, and
  imports only the point-in-time data platform a consumer may use;
* it reads no clock -- every instant is injected;
* its terminal output carries no size, order or credential, structurally;
* the authorized surface is exactly the Brain kernel plus Breakout Long; the other
  strategy packages, and portfolio, risk, research and monitoring, stay empty.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BRAIN_ROOT = PROJECT_ROOT / "src" / "kalpamani" / "strategies" / "brain"
STRATEGIES_ROOT = PROJECT_ROOT / "src" / "kalpamani" / "strategies"

#: Import roots a Brain module may never reach. The kernel data platform is allowed
#: only through its point-in-time and contracts packages (the A1 consumer rule).
FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "socket",
        "ssl",
        "http",
        "urllib",
        "ftplib",
        "asyncio",
        "requests",
        "httpx",
        "urllib3",
        "boto3",
        "botocore",
        "sqlite3",
        "psycopg",
        "psycopg2",
        "sqlalchemy",
    }
)

#: The only kernel data subpackages a consumer may import.
ALLOWED_DATA_PREFIXES = ("kalpamani.data.pit", "kalpamani.data.contracts")

#: Identifiers that would smuggle a non-point-in-time route into the Brain.
FORBIDDEN_IDENTIFIERS = frozenset({"latest", "current", "most_recent", "today"})


def _python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.append(node.module)
    return modules


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


def test_no_brain_module_imports_a_network_provider_or_sdk() -> None:
    offenders: list[str] = []
    for path in _python_files(STRATEGIES_ROOT):
        for module in _imports(path):
            root = module.split(".")[0]
            if root in FORBIDDEN_IMPORT_ROOTS:
                offenders.append(f"{path.relative_to(PROJECT_ROOT)} imports {module}")
    assert offenders == [], offenders


def test_the_brain_imports_only_the_point_in_time_data_platform() -> None:
    offenders: list[str] = []
    for path in _python_files(STRATEGIES_ROOT):
        for module in _imports(path):
            if module.startswith("kalpamani.data") and not module.startswith(ALLOWED_DATA_PREFIXES):
                offenders.append(f"{path.relative_to(PROJECT_ROOT)} imports {module}")
    assert offenders == [], offenders


def test_the_brain_reaches_no_broker_or_execution_package() -> None:
    offenders: list[str] = []
    for path in _python_files(STRATEGIES_ROOT):
        for module in _imports(path):
            if module.startswith(("kalpamani.broker", "kalpamani.execution")):
                offenders.append(f"{path.relative_to(PROJECT_ROOT)} imports {module}")
    assert offenders == [], offenders


def test_the_brain_names_no_non_point_in_time_route() -> None:
    offenders: list[str] = []
    for path in _python_files(STRATEGIES_ROOT):
        hits = _identifiers(path) & FORBIDDEN_IDENTIFIERS
        if hits:
            offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {sorted(hits)}")
    assert offenders == [], offenders


def test_the_brain_reads_no_clock() -> None:
    """The decision instant is injected; nothing in the Brain calls a wall clock.

    ``datetime.now``/``utcnow``, ``date.today``, ``time.time``/``monotonic`` and
    ``time.sleep`` would each make a decision depend on when it ran.
    """
    forbidden_calls = {"now", "utcnow", "today", "monotonic", "sleep"}
    offenders: list[str] = []
    for path in _python_files(STRATEGIES_ROOT):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in forbidden_calls:
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}: .{node.attr}")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in {"time"}:
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}: time()")
    assert offenders == [], offenders


def test_candidate_intent_has_no_forbidden_field_meaning() -> None:
    """The structural exclusion, read from the source: no dataclass field of a
    size, order, route or credential meaning anywhere in the intent module."""
    from dataclasses import fields, is_dataclass
    from importlib import import_module

    intent_module = import_module("kalpamani.strategies.brain.intent")
    # The forbidden *meanings* of ADR-0026 section 2.2, as precise field-name tokens.
    # "liquidity_average_dollar_volume" is a liquidity statistic, not the trade's dollar
    # amount, so the tokens target position/order size and amount, not the bare words.
    forbidden = (
        "shares",
        "share_count",
        "quantity",
        "notional",
        "position_size",
        "order_size",
        "final_size",
        "dollar_amount",
        "position_dollar",
        "order_type",
        "broker_route",
        "client_order",
        "broker_order",
        "credential",
        "account_number",
        "password",
        "secret",
        "api_key",
    )
    offenders: list[str] = []
    for name in dir(intent_module):
        obj = getattr(intent_module, name)
        if isinstance(obj, type) and is_dataclass(obj):
            for field in fields(obj):
                lowered = field.name.lower()
                if any(bad in lowered for bad in forbidden):
                    offenders.append(f"{name}.{field.name}")
    assert offenders == [], offenders


def test_the_authorized_strategy_surface_is_exactly_the_brain_and_breakout_long() -> None:
    """Breakout Long is the one strategy module authorized this cycle. Pullback and PEAD
    stay empty, and no other strategy module appears."""
    breakout = STRATEGIES_ROOT / "breakout"
    breakout_modules = sorted(p.name for p in breakout.glob("*.py") if p.name != "__init__.py")
    assert breakout_modules == ["long.py"]
    for still_empty in ("pullback", "pead"):
        package = STRATEGIES_ROOT / still_empty
        modules = sorted(p.name for p in package.glob("*.py") if p.name != "__init__.py")
        assert modules == [], f"{still_empty} must stay empty this cycle: {modules}"


def test_the_brain_package_holds_exactly_the_authorized_modules() -> None:
    """The Brain kernel surface is fixed; a new module here is an ADR-level change."""
    expected = {
        "__init__.py",
        "vocabulary.py",
        "errors.py",
        "identity.py",
        "evidence.py",
        "factors.py",
        "spec.py",
        "intent.py",
        "gate.py",
        "module.py",
        "consolidation.py",
        "compiler.py",
        "journal.py",
        "health.py",
    }
    present = {p.name for p in BRAIN_ROOT.glob("*.py")}
    assert present == expected, present ^ expected
