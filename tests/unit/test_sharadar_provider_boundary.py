"""Where the provider package may and may not reach, enforced by scan rather than by care.

ADR-0009 authorized provider-specific code for the first time. That widens the
repository's surface in exactly the way a boundary has to be written down before,
not after: vendor knowledge is now allowed *somewhere*, so "nowhere" has stopped
being the rule and something narrower has to take its place.

Four boundaries, and each is a specific way the slice could stop meaning what it
says:

**The A1 kernel stays vendor-neutral.** The point-in-time contract, the query
layer, the neutral writers and the curated layers must not import the provider
package. An adapter feeds evidence *into* the architecture; a kernel that imported
a vendor would have made that vendor part of the contract.

**Nothing outside the package knows the vendor.** Research, strategy, risk and
portfolio code cannot reach ingest at all, and no other production module names
the provider -- so a second, unreviewed integration cannot appear beside this one.

**The network is one dormant object.** Importing the package opens no socket, only
``transport`` reaches for a network module, and nothing in the repository
constructs the concrete transport. A live runner is not authorized in this slice,
and its absence is checked rather than assumed.

**No credential literal exists under ``src/``**, and there is no route from a
vendor payload to an external model provider.

These are AST and text scans over committed files. **Nothing here contacts
Sharadar, AWS or any network.**
"""

from __future__ import annotations

import ast
import importlib
import re
import socket as socket_module
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
PACKAGE_ROOT = SRC / "kalpamani"
DATA_ROOT = PACKAGE_ROOT / "data"
PROVIDER_PACKAGE = DATA_ROOT / "ingest" / "sharadar"
SCRIPTS = PROJECT_ROOT / "scripts"
TESTS = PROJECT_ROOT / "tests"

PROVIDER_MODULE = "kalpamani.data.ingest.sharadar"

#: The vendor-neutral surface the provider package must never appear inside.
NEUTRAL_PACKAGES = (
    DATA_ROOT / "contracts",
    DATA_ROOT / "pit",
    DATA_ROOT / "live",
    DATA_ROOT / "normalize",
    DATA_ROOT / "curate",
    DATA_ROOT / "quality",
)

#: Modules that can open a connection. Only the transport may name one.
NETWORK_MODULES = frozenset({"socket", "ssl", "http", "urllib", "ftplib", "telnetlib", "asyncio"})

#: External model providers. A vendor payload reaching one would breach Sharadar
#: Terms §4 and §8 and CLAUDE.md §4.22 at once.
EXTERNAL_AI_MARKERS = (
    "api.openai.com",
    "api.anthropic.com",
    "generativelanguage.googleapis.com",
    "bedrock-runtime",
    "openai",
    "anthropic",
    "langchain",
)


def python_files(root: Path) -> Iterator[Path]:
    yield from sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def module_package(path: Path) -> str:
    """The package a relative import inside ``path`` resolves against."""
    relative = path.relative_to(SRC).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    dotted = ".".join(parts)
    return dotted if path.name == "__init__.py" else dotted.rpartition(".")[0]


def imported_modules(path: Path) -> set[str]:
    """Every module ``path`` imports -- absolute, aliased and relative alike."""
    anchor = module_package(path)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module or ""
            else:
                parts = anchor.split(".")
                trimmed = parts[: len(parts) - (node.level - 1)] if node.level > 1 else parts
                base = ".".join([*trimmed, node.module] if node.module else trimmed)
            if not base:
                continue
            modules.add(base)
            modules.update(f"{base}.{alias.name}" for alias in node.names)
    return modules


# ---------------------------------------------------------------------------
# I -- the A1 kernel stays vendor-neutral
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("package", [p.name for p in NEUTRAL_PACKAGES])
def test_a_vendor_neutral_data_package_does_not_import_the_provider(package: str) -> None:
    """An adapter feeds evidence into the architecture; it is not part of it."""
    offenders = [
        str(path.relative_to(PROJECT_ROOT))
        for path in python_files(DATA_ROOT / package)
        if any(module.startswith(PROVIDER_MODULE) for module in imported_modules(path))
    ]
    assert offenders == [], f"{package} imports the provider package: {offenders}"


def test_the_neutral_bronze_writers_do_not_import_the_provider() -> None:
    """Storage rules live in the neutral layer, and stay there."""
    for name in ("bronze.py", "publication.py"):
        path = DATA_ROOT / "ingest" / name
        assert not any(m.startswith(PROVIDER_MODULE) for m in imported_modules(path)), (
            f"{name} imports the provider package; the storage rules would then be the "
            "vendor's rather than the contract's"
        )


def test_only_the_provider_package_imports_the_provider_package() -> None:
    offenders = [
        str(path.relative_to(PROJECT_ROOT))
        for path in python_files(PACKAGE_ROOT)
        if not path.is_relative_to(PROVIDER_PACKAGE)
        and any(module.startswith(PROVIDER_MODULE) for module in imported_modules(path))
    ]
    assert offenders == [], f"the provider package is imported from outside it: {offenders}"


def test_no_production_module_outside_the_provider_package_names_the_vendor() -> None:
    """ADR-0009 authorized one integration, in one place. A second cannot appear quietly.

    The neutral packages may *mention* the provider package in prose describing the
    boundary, so the scan is over production modules that are neither inside the
    package nor the two package docstrings that describe the layout.
    """
    described = {DATA_ROOT / "__init__.py", DATA_ROOT / "ingest" / "__init__.py"}
    offenders = [
        str(path.relative_to(PROJECT_ROOT))
        for path in python_files(PACKAGE_ROOT)
        if not path.is_relative_to(PROVIDER_PACKAGE)
        and path not in described
        and "sharadar" in path.read_text(encoding="utf-8").lower()
    ]
    assert offenders == [], f"production code outside the provider package names it: {offenders}"


def test_the_provider_package_does_not_reach_the_brokerage_boundary() -> None:
    offenders = [
        f"{path.relative_to(PROJECT_ROOT)} imports {module}"
        for path in python_files(PROVIDER_PACKAGE)
        for module in imported_modules(path)
        if module.startswith(("kalpamani.broker", "kalpamani.execution"))
    ]
    assert offenders == [], f"the data platform has no brokerage boundary to breach: {offenders}"


def test_the_provider_package_does_not_import_the_point_in_time_query_layer() -> None:
    """Ingestion writes evidence; it does not ask historical questions of it."""
    offenders = [
        f"{path.relative_to(PROJECT_ROOT)} imports {module}"
        for path in python_files(PROVIDER_PACKAGE)
        for module in imported_modules(path)
        if module.startswith(("kalpamani.data.pit", "kalpamani.data.live"))
    ]
    assert offenders == [], f"Found: {offenders}"


def test_the_provider_package_does_not_import_the_qualification_harness() -> None:
    """The manual private harness and the production adapter stay separate programs."""
    offenders = [
        str(path.relative_to(PROJECT_ROOT))
        for path in python_files(PROVIDER_PACKAGE)
        if "sharadar_private_qualification" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"Found: {offenders}"


# ---------------------------------------------------------------------------
# C -- the network boundary
# ---------------------------------------------------------------------------


def test_only_the_transport_module_names_a_network_module() -> None:
    """``urllib.parse`` is exempt, and only ``urllib.parse``.

    It is pure string manipulation -- percent-encoding a query -- and opens
    nothing. ``urllib.request`` is the half that connects, and it is not exempt,
    so an edit that reached for it outside the transport fails here.
    """
    offenders: list[str] = []
    for path in python_files(PROVIDER_PACKAGE):
        if path.name == "transport.py":
            continue
        for module in imported_modules(path):
            if module.split(".")[0] in NETWORK_MODULES and not module.startswith("urllib.parse"):
                offenders.append(f"{path.relative_to(PROJECT_ROOT)} imports {module}")
    assert offenders == [], f"network capability outside the transport: {offenders}"


#: Calls that could reach a network, or install something process-wide that
#: silently changes how a later one behaves.
NETWORK_PRIMITIVES = frozenset(
    {
        "urlopen",
        "build_opener",
        "install_opener",
        "Request",
        "socket",
        "create_connection",
        "getaddrinfo",
        "connect",
        "HTTPConnection",
        "HTTPSConnection",
    }
)


def test_the_transport_opens_nothing_and_installs_nothing_at_module_scope() -> None:
    """A connection made at import time happens before anyone decided to make one.

    Deliberately scoped to network primitives rather than to *any* call. The
    module legitimately parses its own allowed origin at import -- that is pure
    string work over a constant, and forbidding it would push the origin
    constants into hand-copied literals, which is the drift the derivation exists
    to prevent.

    ``install_opener`` is included because installing an opener is a process-wide
    side effect: it would change the behaviour of unrelated code, and would do so
    from an import.
    """
    tree = ast.parse((PROVIDER_PACKAGE / "transport.py").read_text(encoding="utf-8"))
    offenders: list[str] = []
    for statement in tree.body:
        if isinstance(statement, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for node in ast.walk(statement):
            if not isinstance(node, ast.Call):
                continue
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else ""
            )
            if name in NETWORK_PRIMITIVES:
                offenders.append(f"line {node.lineno}: {name}")
    assert offenders == [], f"network primitives at module scope: {offenders}"


def test_no_module_installs_a_global_url_opener() -> None:
    """A globally installed opener would let unrelated code decide how a
    credential-bearing request is routed, and vice versa."""
    offenders = [
        f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}"
        for path in python_files(PACKAGE_ROOT)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "install_opener")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "install_opener")
        )
    ]
    assert offenders == [], f"a global opener is installed at: {offenders}"


def test_the_transport_pins_an_exact_origin_rather_than_a_string_prefix() -> None:
    """``startswith("https://")`` admits a lookalike host and a userinfo prefix."""
    source = (PROVIDER_PACKAGE / "transport.py").read_text(encoding="utf-8")
    for needle in ("urlsplit", "parts.hostname", "parts.username", "parts.fragment", "parts.port"):
        assert needle in source, f"the origin check does not examine {needle}"


def test_importing_the_provider_package_opens_no_socket() -> None:
    """Proven by re-executing the package with sockets disabled, not by reading it."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("importing the provider package opened a socket")

    original_socket = socket_module.socket
    original_connect = socket_module.create_connection
    purged = [name for name in sys.modules if name.startswith(PROVIDER_MODULE)]
    saved = {name: sys.modules[name] for name in purged}
    try:
        socket_module.socket = refuse  # type: ignore[assignment,misc]
        socket_module.create_connection = refuse  # type: ignore[assignment]
        for name in purged:
            del sys.modules[name]
        reloaded = importlib.import_module(PROVIDER_MODULE)
        assert reloaded.PROVIDER == "sharadar"
    finally:
        socket_module.socket = original_socket  # type: ignore[misc]
        socket_module.create_connection = original_connect
        sys.modules.update(saved)


#: The one module allowed to construct the concrete transport. It injects a fake
#: opener and performs no I/O, which is what lets *dormant* stop meaning
#: *untested* without letting a real network transport into the runtime.
TRANSPORT_TEST = TESTS / "unit" / "test_sharadar_transport.py"
#: The operator binding preflight, ADR-0015: the one production caller
#: authorized to construct a real transport, inside a branch that refuses by default.
BINDING_PREFLIGHT = SCRIPTS / "sharadar_binding_preflight.py"
BINDING_PREFLIGHT_TEST = TESTS / "unit" / "test_sharadar_binding_preflight.py"


def test_no_production_module_or_script_constructs_the_concrete_transport() -> None:
    """Dormancy where it still matters. Two named files, and nowhere else.

    The rule was already narrower than "nowhere", because an unconstructed class
    cannot be proven to pin an origin, refuse a redirect or bound a body -- so
    the dedicated synthetic unit test may build one with a fake opener.

    ADR-0015 added the second: the operator binding preflight builds a real
    transport inside a factory that only its authorized branch calls. That is the
    point of the slice, and it is the same trade -- a transport nobody can build
    is a transport nobody can use, and the preflight refuses by default. Every
    other production module, script and unattended runner still fails here.
    """
    allowed = {TRANSPORT_TEST, BINDING_PREFLIGHT, BINDING_PREFLIGHT_TEST}
    offenders: list[str] = []
    for root in (PACKAGE_ROOT, SCRIPTS, TESTS):
        for path in python_files(root):
            if path in allowed:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
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
                if name == "UrllibTransport":
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")
    assert offenders == [], f"the concrete transport is constructed at: {offenders}"


def test_the_one_module_that_may_build_a_transport_injects_a_fake_opener() -> None:
    """The allowlist is only safe while the allowlisted file opens nothing."""
    source = TRANSPORT_TEST.read_text(encoding="utf-8")
    assert "opener=" in source, "the transport test must inject an opener"
    tree = ast.parse(source, filename=str(TRANSPORT_TEST))
    offenders = [
        f"line {node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "UrllibTransport"
        and not any(keyword.arg == "opener" for keyword in node.keywords)
    ]
    assert offenders == [], f"a transport is built without a fake opener at: {offenders}"


def test_the_client_has_no_default_transport() -> None:
    """A client that could reach a network unassisted is one a forgetful test can fire."""
    import inspect

    from kalpamani.data.ingest.sharadar.client import SharadarClient

    parameter = inspect.signature(SharadarClient.__init__).parameters["transport"]
    assert parameter.default is inspect.Parameter.empty
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


def test_the_provider_package_reaches_exactly_one_vendor_host() -> None:
    import re

    hosts = {
        match.group(1)
        for path in python_files(PROVIDER_PACKAGE)
        for match in re.finditer(r"https?://([A-Za-z0-9.\-]+)", path.read_text(encoding="utf-8"))
    }
    assert hosts == {"api.sharadar.com"}, f"unexpected hosts: {sorted(hosts)}"


# ---------------------------------------------------------------------------
# Credential and disclosure surface
# ---------------------------------------------------------------------------


def test_no_api_key_literal_exists_anywhere_under_src() -> None:
    """Not a private key, and not the vendor's published test token either.

    The published token is legitimate in the manual harness under ``scripts/``. A
    value that is harmless there becomes a habit if production code carries one,
    and the habit is what eventually commits a real key.
    """
    offenders = [
        str(path.relative_to(PROJECT_ROOT))
        for path in python_files(SRC)
        if "test-api-key" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"a key literal appears in production code: {offenders}"


def test_the_credential_value_is_reachable_through_exactly_one_named_method() -> None:
    from kalpamani.data.ingest.sharadar.credentials import SharadarCredential

    source = (PROVIDER_PACKAGE / "credentials.py").read_text(encoding="utf-8")
    assert source.count("self._secret") == 2, "the secret should be assigned once and read once"
    public = {name for name in vars(SharadarCredential) if not name.startswith("_")}
    assert public == {"reveal"}


def test_the_credential_is_never_persisted_by_the_publication_path() -> None:
    """The Bronze bridge takes a request and bytes. It has no credential parameter."""
    import inspect

    from kalpamani.data.ingest.sharadar.bronze import (
        publish_sharadar_payload,
        sharadar_retrieval_metadata,
    )

    for function in (publish_sharadar_payload, sharadar_retrieval_metadata):
        parameters = set(inspect.signature(function).parameters)
        assert not parameters & {"credential", "api_key", "url", "client", "transport"}


@pytest.mark.parametrize("marker", EXTERNAL_AI_MARKERS)
def test_no_external_ai_path_exists_for_a_vendor_payload(marker: str) -> None:
    """Services Data and evaluation conclusions have no route to a model provider."""
    offenders = [
        str(path.relative_to(PROJECT_ROOT))
        for path in python_files(PROVIDER_PACKAGE)
        if marker in path.read_text(encoding="utf-8").lower()
    ]
    assert offenders == [], f"{marker!r} appears in the provider package: {offenders}"


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


def test_the_provider_package_declares_no_new_dependency() -> None:
    """Standard library only, and the AWS SDK stays out of the provider package.

    The project acquired one runtime dependency on 2026-08-28 (ADR-0011), and it
    belongs to the storage boundary. A provider adapter that reached the SDK
    would know about buckets, which is exactly what the ``ResearchObjectStore``
    protocol exists to stop it knowing.
    """
    forbidden = {"boto3", "botocore", "requests", "httpx", "urllib3", "pandas", "pyarrow", "duckdb"}
    offenders = [
        f"{path.relative_to(PROJECT_ROOT)} imports {module}"
        for path in python_files(PROVIDER_PACKAGE)
        for module in imported_modules(path)
        if module.split(".")[0] in forbidden
    ]
    assert offenders == [], f"Found: {offenders}"
    assert declared_runtime_dependencies() == AUTHORIZED_RUNTIME_DEPENDENCIES
