"""The production task image entrypoint script: dormant on import, closed on selection.

The script is loaded by path, the way every operator-surface test loads one, and its
``main`` is driven directly. Every path exercised here refuses **before** a factory is
called: no SDK client, no socket and no metadata read exists in this file's execution.
**Nothing here is AWS or provider verification.**
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import tempfile
import types
from pathlib import Path
from typing import Any, Final

import pytest

from fixtures.production_entry import ORIGIN_ADDRESSES
from fixtures.production_runtime import compiled_task
from kalpamani.data.production.sharadar.entry import (
    EXIT_STATUS,
    EntryConfiguration,
    TaskEntry,
    TaskOutcome,
    task_sentence,
)
from kalpamani.data.production.sharadar.vocabulary import ProductionActor

pytestmark = pytest.mark.unit

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
SCRIPT: Final = REPO_ROOT / "scripts" / "production_task_entrypoint.py"
SOURCE: Final = SCRIPT.read_text(encoding="utf-8")


def _module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        pytest.fail("the entry point could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


entrypoint = _module("production_task_entrypoint", SCRIPT)


def _executable(source: str) -> str:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.ClassDef) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                node.body = node.body[1:] or [ast.Pass()]
    return ast.unparse(tree)


EXECUTABLE: Final = _executable(SOURCE)


# ---------------------------------------------------------------------------
# Dormant on import
# ---------------------------------------------------------------------------


def test_no_kalpamani_or_sdk_import_happens_at_module_level() -> None:
    for node in ast.parse(SOURCE).body:
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith(("kalpamani", "boto3", "botocore"))
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith(("kalpamani", "boto3", "botocore", "urllib"))


def test_no_environment_read_or_construction_happens_at_module_level() -> None:
    for node in ast.parse(SOURCE).body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.If):
            continue
        text = ast.unparse(node)
        assert "os.environ" not in text and "client(" not in text and "urlopen" not in text


def test_the_two_entry_names_are_the_task_definitions_command_tokens() -> None:
    compute = (
        REPO_ROOT / "infra" / "aws" / "research-data-plane" / "production_compute.tf"
    ).read_text(encoding="utf-8")
    for entry in TaskEntry:
        assert f'command   = ["{entry.value}"]' in compute


# ---------------------------------------------------------------------------
# Selection refuses before anything exists
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [[], ["--help"], ["acquire"], ["kalpamani-production-acquire", "x"], ["--actor", "build"]],
)
def test_anything_but_one_closed_token_refuses_with_nothing_built(
    argv: list[str], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(entrypoint, "_factories", _fail("factories"))
    monkeypatch.setattr(entrypoint, "_compiled_configuration", _fail("configuration"))
    assert entrypoint.main(argv) == 2 == EXIT_STATUS[TaskOutcome.REFUSED_ENTRY]
    out = capsys.readouterr()
    assert out.out.strip() == task_sentence(TaskOutcome.REFUSED_ENTRY) and out.err == ""


def _fail(what: str) -> Any:
    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"{what} must not be reached")

    return refuse


@pytest.mark.parametrize("entry", list(TaskEntry))
def test_an_absent_compiled_configuration_refuses_before_any_factory(
    entry: TaskEntry, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delitem(sys.modules, entrypoint.COMPILED_CONFIGURATION_MODULE, raising=False)
    monkeypatch.setattr(entrypoint, "_factories", _fail("factories"))
    assert entrypoint.main([entry.value]) == EXIT_STATUS[TaskOutcome.REFUSED_CONFIGURATION] == 3
    assert capsys.readouterr().out.strip() == task_sentence(TaskOutcome.REFUSED_CONFIGURATION)


def test_a_compiled_module_without_the_builder_or_raising_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(entrypoint, "_factories", _fail("factories"))
    empty = types.ModuleType(entrypoint.COMPILED_CONFIGURATION_MODULE)
    monkeypatch.setitem(sys.modules, entrypoint.COMPILED_CONFIGURATION_MODULE, empty)
    assert entrypoint.main([TaskEntry.BUILD.value]) == 3
    raising = types.ModuleType(entrypoint.COMPILED_CONFIGURATION_MODULE)
    raising.entry_configuration = _fail("builder")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, entrypoint.COMPILED_CONFIGURATION_MODULE, raising)
    assert entrypoint.main([TaskEntry.BUILD.value]) == 3


def test_the_compiled_module_is_absent_from_this_repository() -> None:
    assert importlib.util.find_spec(entrypoint.COMPILED_CONFIGURATION_MODULE) is None


# ---------------------------------------------------------------------------
# With a compiled configuration, the real entry runs and refuses on the workstation
# ---------------------------------------------------------------------------


def _compiled(entry: TaskEntry) -> EntryConfiguration:
    actor = ProductionActor.ACQUISITION if entry is TaskEntry.ACQUISITION else ProductionActor.BUILD
    if entry is TaskEntry.ACQUISITION:
        return EntryConfiguration(
            entry=entry,
            compiled=compiled_task(actor),
            secret_identifier="synthetic/production/sharadar",  # noqa: S106 - an identifier
            origin_addresses=ORIGIN_ADDRESSES,
        )
    from fixtures.production_build import configuration

    return EntryConfiguration(
        entry=entry, compiled=compiled_task(actor), build_configuration=configuration()
    )


@pytest.mark.parametrize("entry", list(TaskEntry))
def test_on_a_workstation_the_credential_environment_refuses_before_any_client(
    entry: TaskEntry,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The real factories are built; none is called: the environment refuses first."""
    compiled = types.ModuleType(entrypoint.COMPILED_CONFIGURATION_MODULE)
    compiled.entry_configuration = _compiled  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, entrypoint.COMPILED_CONFIGURATION_MODULE, compiled)
    monkeypatch.setattr(entrypoint, "_client", _fail("client construction"))
    monkeypatch.setattr(entrypoint, "_transport", _fail("transport construction"))
    monkeypatch.setattr(entrypoint, "_metadata_fetch", _fail("metadata fetch"))
    monkeypatch.setattr(entrypoint, "_resolve_origin", _fail("origin resolution"))
    # A workstation: a profile is set and no container credential provider exists.
    monkeypatch.setenv("AWS_PROFILE", "synthetic-profile")
    monkeypatch.delenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", raising=False)
    monkeypatch.delenv("AWS_CONTAINER_CREDENTIALS_FULL_URI", raising=False)
    monkeypatch.setattr(tempfile, "mkdtemp", lambda prefix: str(tmp_path / "work"))
    (tmp_path / "work").mkdir()
    code = entrypoint.main([entry.value])
    assert code == EXIT_STATUS[TaskOutcome.REFUSED_CREDENTIAL_ENVIRONMENT] == 4
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == task_sentence(TaskOutcome.REFUSED_CREDENTIAL_ENVIRONMENT)
    assert "counts_observed=true" in lines and "s3_operations=0" in lines
    assert "synthetic-profile" not in "\n".join(lines)
    assert not (tmp_path / "work").exists()  # the working directory was cleaned up


def test_the_task_side_spent_identity_source_is_not_configured() -> None:
    assert "spent_identities=None" in EXECUTABLE
    assert (
        "LedgerSpentIdentities" not in EXECUTABLE and "UnavailableSpentIdentities" not in EXECUTABLE
    )


def test_the_metadata_fetch_is_pinned_and_proxyless() -> None:
    assert "ProxyHandler" not in EXECUTABLE and "build_opener" not in EXECUTABLE
    assert "OpenerDirector()" in EXECUTABLE and "HTTPHandler()" in EXECUTABLE
    assert "http://169.254.170.2/v4/" in EXECUTABLE


def test_no_option_or_argv_value_is_ever_echoed(capsys: pytest.CaptureFixture[str]) -> None:
    entrypoint.main(["--secret", "AKIASYNTHETICVALUE000"])
    assert "AKIA" not in capsys.readouterr().out
