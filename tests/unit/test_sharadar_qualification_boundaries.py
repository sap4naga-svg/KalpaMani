"""The boundaries that keep the qualification runtime dormant, checked by scan.

ADR-0012 authorized a runtime core that *could* execute a plan if it were handed a
real client and a real store. The distance between that and a runtime that
actually reaches Sharadar or AWS is exactly one composition root -- and this file
is the record that none exists.

Two kinds of check live here:

**Structural.** AST and text scans over committed files, proving the new modules
import no network client and no SDK, construct no client or session, read no
environment variable and no file, and hold no global mutable state.

**Behavioural, for the command-line surface.** The plan-check command is run
in-process with argument lists and its output inspected. It has no execution mode,
and the options that would imply one are refused by name.

**Nothing here contacts Sharadar, AWS or any network**, and several tests exist
specifically to establish that nothing it covers could.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
PROVIDER_PACKAGE = SRC / "kalpamani" / "data" / "ingest" / "sharadar"
QUALIFICATION = PROVIDER_PACKAGE / "qualification.py"
RUNTIME = PROVIDER_PACKAGE / "runtime.py"
COMPOSITION = PROVIDER_PACKAGE / "composition.py"
PLAN_CHECK = PROJECT_ROOT / "scripts" / "sharadar_plan_check.py"
PRIVATE_HARNESS = PROJECT_ROOT / "scripts" / "sharadar_private_qualification.py"

#: The two modules the ADR-0012 slice added. Named individually so a third
#: appearing beside them has to pass review rather than merely compile.
#:
#: Used for the one check the composition root is *exempt* from -- constructing a
#: client, a session or a store -- because building those from injected values is
#: exactly what ADR-0014 authorized it to do.
NEW_MODULES = (QUALIFICATION, RUNTIME)

#: Every module that must stay dormant, the composition root included.
#:
#: The composition root builds things; it still may not import a network client
#: or an SDK, read an environment variable or a file, name a host, bucket, ARN or
#: account, carry an entry point, or hold module-level mutable state. Those are
#: the properties that keep a constructed component inert, and they apply to the
#: module that constructs it more than to any other.
DORMANT_MODULES = (QUALIFICATION, RUNTIME, COMPOSITION)

#: Distributions the runtime core may not import. Wider than the repository-wide
#: rule on purpose: `boto3` is a declared dependency of the project (ADR-0011) and
#: exactly one module may name it, which is not one of these.
FORBIDDEN_IMPORTS = (
    "boto3",
    "botocore",
    "urllib",
    "requests",
    "httpx",
    "urllib3",
    "socket",
    "ssl",
    "http",
    "ftplib",
    "smtplib",
    "subprocess",
    "pandas",
    "pyarrow",
    "duckdb",
    "openai",
    "anthropic",
)

#: Names whose construction would create the composition root this slice
#: deliberately does not have.
FORBIDDEN_CONSTRUCTIONS = (
    "S3ResearchObjectStore",
    "UrllibTransport",
    "SharadarCredential",
    "Session",
    "client",
    "resource",
    "credential_from_env",
)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def _executable(path: Path) -> str:
    """The module's code with every docstring removed.

    A scan over raw source would fire on the prose explaining what a module
    refuses to do, which would either weaken the guard or forbid saying why it
    exists.
    """
    tree = _tree(path)
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


# ---------------------------------------------------------------------------
# The runtime core cannot reach a network or a cloud
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", DORMANT_MODULES, ids=lambda p: p.name)
def test_the_new_modules_import_no_network_client_or_sdk(path: Path) -> None:
    offenders = [module for module in _imported(path) if module.split(".")[0] in FORBIDDEN_IMPORTS]
    assert offenders == [], f"{path.name} imports {offenders}"


@pytest.mark.parametrize("path", NEW_MODULES, ids=lambda p: p.name)
def test_the_new_modules_construct_no_client_session_or_store(path: Path) -> None:
    """A composition root is what turns a dormant core into a live one."""
    offenders: list[str] = []
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.Call):
            continue
        name = (
            node.func.id
            if isinstance(node.func, ast.Name)
            else node.func.attr
            if isinstance(node.func, ast.Attribute)
            else ""
        )
        if name in FORBIDDEN_CONSTRUCTIONS:
            offenders.append(f"{path.name}:{node.lineno} {name}")
    assert offenders == [], f"a composition root is not authorized. Found: {offenders}"


@pytest.mark.parametrize("path", DORMANT_MODULES, ids=lambda p: p.name)
def test_the_new_modules_read_no_environment_and_no_file(path: Path) -> None:
    """Ambient discovery is how a test run ends up holding a credential."""
    source = _executable(path)
    for reader in ("os.environ", "getenv", "open(", "Path(", "read_text", "read_bytes", "dotenv"):
        assert reader not in source, f"{path.name} performs ambient discovery via {reader!r}"


@pytest.mark.parametrize("path", DORMANT_MODULES, ids=lambda p: p.name)
def test_the_new_modules_name_no_host_bucket_arn_or_account(path: Path) -> None:
    source = _executable(path)
    assert re.search(r"(https?://|s3://|arn:aws|amazonaws\.com|\b\d{12}\b)", source) is None


@pytest.mark.parametrize("path", DORMANT_MODULES, ids=lambda p: p.name)
def test_the_new_modules_have_no_entry_point(path: Path) -> None:
    source = _executable(path)
    assert '__name__ == "__main__"' not in source
    assert "argparse" not in source


@pytest.mark.parametrize("path", DORMANT_MODULES, ids=lambda p: p.name)
def test_the_new_modules_hold_no_global_mutable_state(path: Path) -> None:
    """A module-level list or dict is state two runs would share."""
    offenders: list[str] = []
    for node in _tree(path).body:
        if not isinstance(node, ast.Assign | ast.AnnAssign):
            continue
        value = node.value
        if isinstance(value, ast.List | ast.Dict | ast.Set):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                # `__all__` is a language convention rather than state: nothing
                # reads it at run time, and mutating it would change an export
                # list, not a run. Every other module-level container is refused.
                if isinstance(target, ast.Name) and target.id != "__all__":
                    offenders.append(f"{path.name}:{node.lineno} {target.id}")
    assert offenders == [], f"module-level mutable state: {offenders}"


def test_the_runtime_publishes_only_through_the_bronze_bridge() -> None:
    """No second storage abstraction, and no route around the neutral publisher."""
    source = _executable(RUNTIME)
    assert "publish_sharadar_payload" in source
    for bypass in ("put_if_absent(", "put_object", "head_object", "ObjectKey."):
        assert bypass not in source, f"the runtime reaches storage directly via {bypass!r}"


def test_the_runtime_never_uses_retrieval_metadata_notes() -> None:
    """`notes` is a free-text field with no durable destination on this path; using
    it as an attestation or a control channel would make it one by accident."""
    assert "notes" not in _executable(RUNTIME)
    assert "notes" not in _executable(QUALIFICATION)


def test_nothing_in_the_repository_constructs_the_runtime_outside_its_own_tests() -> None:
    """Dormancy where it still matters: one composition root, and no runner.

    ADR-0014 authorized exactly one production module to build a runtime. That
    is narrower than "nowhere", and much narrower than "anywhere in the provider
    package": a script, a task, a second composition module or an ad-hoc caller
    still fails here, which is the property that keeps the core dormant.
    """
    allowed = {
        COMPOSITION,
        PROJECT_ROOT / "tests" / "unit" / "test_sharadar_qualification_runtime.py",
        PROJECT_ROOT / "tests" / "unit" / "test_sharadar_qualification_boundaries.py",
        PROJECT_ROOT / "tests" / "unit" / "test_sharadar_composition_preflight.py",
    }
    offenders: list[str] = []
    for root in (SRC, PROJECT_ROOT / "scripts", PROJECT_ROOT / "tests"):
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts or path in allowed:
                continue
            for node in ast.walk(_tree(path)):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "QualificationRuntime"
                ):
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")
    assert offenders == [], f"a qualification runtime is constructed at: {offenders}"


def test_only_the_composition_root_constructs_a_sharadar_client() -> None:
    """The client needs a credential and a transport, so building one *is* the
    composition root -- and ADR-0014 put it in exactly one module.

    The credential is still a parameter there. Constructing a client from an
    injected credential sends nothing; what would send something is a credential
    source, and none exists anywhere.
    """
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts or path == COMPOSITION:
            continue
        for node in ast.walk(_tree(path)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "SharadarClient"
            ):
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")
    assert offenders == [], f"a client is constructed under src/ at: {offenders}"


def test_importing_the_runtime_module_runs_nothing() -> None:
    """Import time must contain no statement that does work.

    The module docstring is the one bare expression allowed, because it is a
    string literal the interpreter files away rather than a call.
    """
    for path in NEW_MODULES:
        body = _tree(path).body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body = body[1:]
        for node in body:
            assert not isinstance(node, ast.Expr | ast.While | ast.For | ast.With), (
                f"{path.name} performs work at import time on line {node.lineno}"
            )


# ---------------------------------------------------------------------------
# The plan-check command
# ---------------------------------------------------------------------------


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    from sharadar_plan_check import main

    code = main(argv)
    return code, capsys.readouterr().out


@pytest.fixture(autouse=True)
def _importable_scripts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``scripts/`` importable without installing it."""
    monkeypatch.syspath_prepend(str(PROJECT_ROOT / "scripts"))


def test_the_command_validates_a_plan_and_reports_a_fixed_schema(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out = _run(
        ["--subject", "ZZQA", "--dataset", "tickers", "--execution-id", "synthetic-exec-0001"],
        capsys,
    )
    assert code == 0
    assert "PLAN OK" in out
    assert "mode                      PLAN VALIDATION ONLY" in out
    assert "plan.requests             1" in out
    assert "plan.profile              PROVIDER_REALISTIC_PIT" in out


def test_the_command_prints_no_subject_symbol(capsys: pytest.CaptureFixture[str]) -> None:
    """Counts and dataset names only, so a transcript is safe to paste anywhere."""
    _, out = _run(
        ["--subject", "ZZQA", "--dataset", "tickers", "--execution-id", "synthetic-exec-0001"],
        capsys,
    )
    assert "ZZQA" not in out


@pytest.mark.parametrize(
    "option",
    ["--execute", "--live", "--api-key", "--secret", "--bucket", "--aws-profile", "--endpoint"],
)
def test_the_command_refuses_every_live_or_secret_option(
    option: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _run([option, "anything"], capsys)
    assert code == 2
    assert out.startswith(f"REFUSED {option}:")
    assert "PLAN OK" not in out


@pytest.mark.parametrize("option", ["--execute=1", "--api-key=synthetic-fake-value"])
def test_an_equals_form_is_refused_too(option: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _run([option], capsys)
    assert code == 2
    assert "REFUSED" in out
    assert "synthetic-fake-value" not in out


def test_the_command_refuses_an_unsupported_query_parameter(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out = _run(["--subject", "ZZQA", "--dataset", "tickers", "--parameter", "years"], capsys)
    assert code == 2
    assert "PLAN REFUSED              PARAMETER_UNSUPPORTED" in out


def test_the_command_refuses_a_windowed_dataset_with_no_window(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out = _run(["--subject", "ZZQA", "--dataset", "stocks"], capsys)
    assert code == 2
    assert "WINDOW_REQUIRED" in out


def test_the_command_refuses_a_malformed_window_without_echoing_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out = _run(
        ["--subject", "ZZQA", "--dataset", "stocks", "--window-start", "not-a-date"], capsys
    )
    assert code == 2
    assert "WINDOW_MALFORMED" in out
    assert "not-a-date" not in out


def test_the_command_refuses_a_plan_with_no_subject(capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _run(["--dataset", "tickers"], capsys)
    assert code == 2
    assert "SUBJECT_MISSING" in out


def test_the_command_offers_only_the_three_stage_3a_datasets(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sharadar_plan_check import build_parser

    action = next(a for a in build_parser()._actions if a.dest == "dataset")
    assert set(action.choices or ()) == {"tickers", "stocks", "actions"}
    with pytest.raises(SystemExit):
        _run(["--dataset", "fundamentals"], capsys)


def test_the_command_imports_no_client_transport_store_or_runtime() -> None:
    """The absence of an execution mode is structural, not a policy."""
    imported = _imported(PLAN_CHECK)
    for module in ("client", "transport", "runtime", "credentials", "storage", "objectstore"):
        assert not any(module in name for name in imported), f"plan-check imports {module}"


def test_the_command_imports_no_network_client_or_sdk() -> None:
    offenders = [
        module for module in _imported(PLAN_CHECK) if module.split(".")[0] in FORBIDDEN_IMPORTS
    ]
    assert offenders == [], f"the plan-check command imports {offenders}"


def test_the_command_does_not_touch_the_private_harness() -> None:
    """A separate, owner-only tool that remains unauthorized to execute."""
    source = PLAN_CHECK.read_text(encoding="utf-8")
    assert "import sharadar_private_qualification" not in source
    assert "private_qualification" not in _executable(PLAN_CHECK)
    assert PRIVATE_HARNESS.is_file(), "the harness must still exist, unmodified"


def test_the_command_opens_no_socket(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("the plan-check command must not open a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    code, _ = _run(
        [
            "--subject",
            "ZZQA",
            "--dataset",
            "stocks",
            "--window-start",
            "2024-01-02",
            "--window-end",
            "2024-03-28",
            "--execution-id",
            "synthetic-exec-0001",
        ],
        capsys,
    )
    assert code == 0


def test_the_command_prints_the_compiled_ceilings(capsys: pytest.CaptureFixture[str]) -> None:
    """A run's bounds should be readable without opening the source."""
    _, out = _run(
        ["--subject", "ZZQA", "--dataset", "tickers", "--execution-id", "synthetic-exec-0001"],
        capsys,
    )
    for line in (
        "ceiling.subjects",
        "ceiling.requests",
        "ceiling.run_bytes",
        "ceiling.retry_budget",
    ):
        assert line in out


def test_the_command_declares_zero_activity(capsys: pytest.CaptureFixture[str]) -> None:
    _, out = _run(
        ["--subject", "ZZQA", "--dataset", "tickers", "--execution-id", "synthetic-exec-0001"],
        capsys,
    )
    for line in (
        "network.sockets           0",
        "network.provider_requests 0",
        "aws.requests              0",
        "credentials.read          0",
    ):
        assert line in out


# ---------------------------------------------------------------------------
# The private harness is untouched
# ---------------------------------------------------------------------------


def test_no_new_module_or_script_imports_the_private_harness() -> None:
    offenders: list[str] = []
    for path in (*NEW_MODULES, PLAN_CHECK):
        if any("private_qualification" in name for name in _imported(path)):
            offenders.append(path.name)
    assert offenders == []


def test_the_published_test_token_appears_nowhere_new() -> None:
    """It belongs to the manual harness, and running that harness is unauthorized."""
    for path in (*NEW_MODULES, PLAN_CHECK):
        source = path.read_text(encoding="utf-8")
        assert not re.search(r"api_key\s*=\s*['\"][A-Za-z0-9_\-]{8,}", source)
        assert "test_token" not in source.lower().replace("published test token", "")
