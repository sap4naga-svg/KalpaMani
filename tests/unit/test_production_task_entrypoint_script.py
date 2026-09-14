"""The production task image entrypoint script: dormant on import, closed on selection.

The script is loaded by path, the way every operator-surface test loads one, and its
``main`` is driven directly. Every path exercised here refuses **before** a factory is
called: no SDK client, no socket and no metadata read exists in this file's execution.
**Nothing here is AWS or provider verification.**
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path
from typing import Any, Final

import pytest

from fixtures.production_entry import ORIGIN_ADDRESSES
from fixtures.production_runtime import COMMIT, NOW, TREE
from kalpamani.data.production.sharadar import receipts as pr
from kalpamani.data.production.sharadar.compiled import (
    COMPILED_CONFIGURATION_PATH,
    build_compiled_configuration,
)
from kalpamani.data.production.sharadar.entry import (
    EXIT_STATUS,
    TaskEntry,
    TaskOutcome,
    task_sentence,
)

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


def _fail(what: str) -> Any:
    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"{what} must not be reached")

    return refuse


def _nothing_external(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every seam that could construct, look up, fetch or resolve anything refuses."""
    for name in (
        "_factories",
        "_client",
        "_isolated_session",
        "_transport",
        "_metadata_fetch",
        "_resolve_origin",
        "_environment_names",
        "_environment",
    ):
        monkeypatch.setattr(entrypoint, name, _fail(name))
    monkeypatch.setattr(tempfile, "mkdtemp", _fail("working directory"))


def _early_refusal_receipt(out: str, *, outcome: TaskOutcome) -> dict[str, Any]:
    """The one structured receipt of an early refusal, with its human-readable lines held.

    Exactly one ``receipt:`` line, last; the allowlisted sentence first; the zero counts
    the process can prove between them; no bootstrap line, because no bootstrap ran.
    """
    lines = out.splitlines()
    assert lines[0] == task_sentence(outcome)
    receipts = [line for line in lines if line.startswith(pr.RECEIPT_LINE_PREFIX)]
    assert len(receipts) == 1 and lines[-1] == receipts[0]
    assert not any(line.startswith("bootstrap:") for line in lines)
    assert "counts_observed=true" in lines
    counts = {line.split("=")[0]: line.split("=")[1] for line in lines[1:-1] if "=" in line}
    assert counts.pop("counts_observed") == "true"
    assert set(counts.values()) == {"0"}
    document = pr.decode_receipt_line(receipts[0])
    assert document["outcome"] == outcome.value
    assert document["exit_code"] == EXIT_STATUS[outcome]
    assert document["runner"] is None and document["binding_digest"] is None
    assert document["code_commit"] is None and document["configuration_digest"] is None
    assert document["counts_observed"] is True and set(document["counts"].values()) == {0}
    assert document["cleanup_failures"] == []
    return document


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--help"],
        ["acquire"],
        ["kalpamani-production-acquire", "extra-argument"],
        ["--actor", "kalpamani-research-build"],
    ],
)
def test_anything_but_one_closed_token_refuses_with_nothing_built(
    argv: list[str], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An invalid invocation names no entry and no actor, and still closes with a receipt."""
    _nothing_external(monkeypatch)
    monkeypatch.setattr(entrypoint, "_compiled_configuration", _fail("configuration"))
    assert entrypoint.main(argv) == 2 == EXIT_STATUS[TaskOutcome.REFUSED_ENTRY]
    assert entrypoint.NO_ENTRY_EXIT_STATUS == EXIT_STATUS[TaskOutcome.REFUSED_ENTRY]
    out = capsys.readouterr()
    assert out.err == ""
    document = _early_refusal_receipt(out.out, outcome=TaskOutcome.REFUSED_ENTRY)
    assert document["entry"] is None and document["actor"] is None
    # No argument value is echoed anywhere -- not even a closed entry name that was
    # passed beside a flag -- and no actor or entry name is invented.
    for value in argv:
        assert value not in out.out
    for entry in TaskEntry:
        assert entry.value not in out.out
    assert '"actor":"' not in out.out and '"entry":"' not in out.out
    # The line the collector will read verifies against any launch record's expectation
    # (the entry is bound through the launch record, not the receipt) and completes a
    # REFUSED ledger row without inventing a count.
    expectation = _expectation(TaskEntry.BUILD)
    verified = pr.collect_and_verify(out.out.splitlines(), expectation=expectation)
    assert verified.entry is None and verified.outcome is TaskOutcome.REFUSED_ENTRY
    assert not verified.released and verified.ledger_outcome == "REFUSED"


def _expectation(entry: TaskEntry) -> pr.ReceiptExpectation:
    from fixtures.production_build import BUILD_NOW, RUN_1  # noqa: F401 - RUN_1 is the identity
    from fixtures.production_runtime import (
        BUILD_ID,
        CONFIGURATION_DIGEST,
        IMAGE_DIGEST,
        TASK_ID,
        revision_arn,
    )
    from kalpamani.data.production.sharadar.vocabulary import ProductionActor

    actor = ProductionActor.ACQUISITION if entry is TaskEntry.ACQUISITION else ProductionActor.BUILD
    return pr.ReceiptExpectation(
        entry=entry,
        task_id=TASK_ID,
        task_definition_arn=revision_arn(actor),
        image_digest=IMAGE_DIGEST,
        configuration_digest=CONFIGURATION_DIGEST,
        code_commit=COMMIT,
        identity=RUN_1 if entry is TaskEntry.ACQUISITION else BUILD_ID,
        input_digest="ab" * 32,
    )


@pytest.mark.parametrize("entry", list(TaskEntry))
def test_an_absent_compiled_configuration_refuses_before_any_factory(
    entry: TaskEntry, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert not Path(entrypoint.COMPILED_CONFIGURATION_PATH).exists()
    _nothing_external(monkeypatch)
    assert entrypoint.main([entry.value]) == EXIT_STATUS[TaskOutcome.REFUSED_CONFIGURATION] == 3
    out = capsys.readouterr()
    assert out.err == ""
    document = _early_refusal_receipt(out.out, outcome=TaskOutcome.REFUSED_CONFIGURATION)
    # The selected entry is named; nothing the absent file would have supplied is.
    assert document["entry"] == entry.value
    verified = pr.collect_and_verify(out.out.splitlines(), expectation=_expectation(entry))
    assert verified.entry is entry and verified.ledger_outcome == "REFUSED"
    # ... and a receipt naming the wrong entry does not bind to this launch record.
    other = TaskEntry.BUILD if entry is TaskEntry.ACQUISITION else TaskEntry.ACQUISITION
    with pytest.raises(pr.ReceiptError) as refusal:
        pr.collect_and_verify(out.out.splitlines(), expectation=_expectation(other))
    assert refusal.value.defect is pr.ReceiptDefect.ENTRY_MISMATCH


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"{not json",
        b"[]",
        b"\xef\xbb\xbf{}",
        b"{" + b" " * (256 * 1024) + b"}",
        b'{"entry":[]}',
        b'{"entry":{"kalpamani-research-build":1}}',
        b'{"entry":"kalpamani-research-build","entry":"kalpamani-research-build"}',
        b'{"entry":"kalpamani-research-build","schema_version":"1"}',
        b'{"entry":"\\udc80"}',
        b"\xff\xfe{}",
    ],
    ids=[
        "empty",
        "not-json",
        "not-an-object",
        "bom",
        "oversize",
        "entry-is-a-list",
        "entry-is-an-object",
        "duplicate-key",
        "missing-fields",
        "lone-surrogate",
        "invalid-utf8",
    ],
)
def test_a_malformed_compiled_configuration_file_refuses(
    content: bytes,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Every malformed file is the closed refusal, with the receipt, and never a raw error."""
    file = tmp_path / "compiled-configuration.json"
    file.write_bytes(content)
    monkeypatch.setattr(entrypoint, "COMPILED_CONFIGURATION_PATH", str(file))
    _nothing_external(monkeypatch)
    assert entrypoint.main([TaskEntry.BUILD.value]) == 3
    out = capsys.readouterr()
    assert out.err == ""
    document = _early_refusal_receipt(out.out, outcome=TaskOutcome.REFUSED_CONFIGURATION)
    assert document["entry"] == TaskEntry.BUILD.value
    assert "Traceback" not in out.out and "not json" not in out.out


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["build_configuration"]["calendar"]["sessions"][0].__setitem__(
            "open_at", "1990-01-01T00:00:00+00:00"
        ),
        lambda d: d["build_configuration"]["evidence"].__setitem__(
            "items",
            [
                {
                    "kind": "PER_VERSION_DELIVERY",
                    "dataset": "stocks",
                    "row_key": ["x"],
                    "content_sha256": None,
                    "instant": None,
                    "evidence_digest": "short",
                }
            ],
        ),
        lambda d: d["build_configuration"]["accepted_schemas"].__setitem__(
            "digests", {"stocks": [{"nested": "dict"}]}
        ),
        lambda d: d["build_configuration"].__setitem__("decision_sessions", [["2026-01-02"]]),
        lambda d: d["build_configuration"]["universe_rule"].__setitem__("history_sessions", "5"),
        lambda d: d["build_configuration"].__setitem__("jump_ratio", 1.5),
    ],
    ids=[
        "session-opens-before-its-date",
        "short-evidence-digest",
        "dict-where-digest-string-expected",
        "list-where-date-expected",
        "string-where-int-expected",
        "float-where-decimal-string-expected",
    ],
)
def test_a_structurally_wrong_build_configuration_is_the_closed_refusal(
    mutate: Any, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The accepted value contracts' own exceptions never escape the entrypoint."""
    document = json.loads(_compiled_bytes(TaskEntry.BUILD))
    mutate(document)
    file = tmp_path / "compiled-configuration.json"
    file.write_bytes(json.dumps(document).encode("utf-8"))
    monkeypatch.setattr(entrypoint, "COMPILED_CONFIGURATION_PATH", str(file))
    _nothing_external(monkeypatch)
    assert entrypoint.main([TaskEntry.BUILD.value]) == 3
    out = capsys.readouterr()
    _early_refusal_receipt(out.out, outcome=TaskOutcome.REFUSED_CONFIGURATION)


def test_a_file_compiled_for_the_other_entry_refuses(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Cross-actor configuration: a build image must not run the acquisition entry."""
    file = tmp_path / "compiled-configuration.json"
    file.write_bytes(_compiled_bytes(TaskEntry.BUILD))
    monkeypatch.setattr(entrypoint, "COMPILED_CONFIGURATION_PATH", str(file))
    _nothing_external(monkeypatch)
    assert entrypoint.main([TaskEntry.ACQUISITION.value]) == 3
    out = capsys.readouterr()
    document = _early_refusal_receipt(out.out, outcome=TaskOutcome.REFUSED_CONFIGURATION)
    # The receipt names the entry that was invoked -- never the file's actor, and
    # never the digest of a file this entry refused to run with.
    assert document["entry"] == TaskEntry.ACQUISITION.value
    assert document["configuration_digest"] is None


def test_the_compiled_file_is_absent_from_this_repository_and_this_workstation() -> None:
    """No TRACKED file is a compiled configuration, and the image path is absent here.

    The generator's git-ignored staging directory (``docker/production/build/``) may hold
    one on a workstation that followed the documented procedure; that is a generated,
    untracked input and not the repository, so the check reads Git's index rather than
    the checkout.
    """
    import shutil
    import subprocess

    assert not Path(entrypoint.COMPILED_CONFIGURATION_PATH).exists()
    assert entrypoint.COMPILED_CONFIGURATION_PATH == COMPILED_CONFIGURATION_PATH
    git = shutil.which("git")
    if git is None:  # pragma: no cover - the repository's own tests need git
        pytest.skip("git is not available")
    tracked = subprocess.run(  # noqa: S603
        [git, "ls-files", "--", "*compiled-configuration.json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert tracked.strip() == ""
    staging = REPO_ROOT / "docker" / "production" / "build"
    ignored = subprocess.run(  # noqa: S603
        [git, "check-ignore", "-q", str(staging / "x")], cwd=REPO_ROOT, check=False
    )
    assert ignored.returncode == 0  # the staging directory is git-ignored


# ---------------------------------------------------------------------------
# With a compiled configuration, the real entry runs and refuses on the workstation
# ---------------------------------------------------------------------------


def _compiled_bytes(entry: TaskEntry) -> bytes:
    """A synthetic compiled configuration file for ``entry``, as the image gate would write."""
    from fixtures.production_build import configuration

    if entry is TaskEntry.ACQUISITION:
        return build_compiled_configuration(
            entry=entry,
            code_commit=COMMIT,
            code_tree=TREE,
            generated_at=NOW,
            secret_name="synthetic/production/sharadar",  # noqa: S106 - a name, not a value
            origin_addresses=sorted(ORIGIN_ADDRESSES),
        )
    return build_compiled_configuration(
        entry=entry,
        code_commit=COMMIT,
        code_tree=TREE,
        generated_at=NOW,
        build_configuration=configuration(),
    )


@pytest.mark.parametrize("entry", list(TaskEntry))
def test_on_a_workstation_the_credential_environment_refuses_before_any_client(
    entry: TaskEntry,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Nothing is built and nothing is created: the environment refuses first.

    The refusal precedes the working directory (the accepted entrypoint created one and
    cleaned it up; a process that is not a task's now creates nothing), so ``mkdtemp``
    must never be reached, and the receipt carries the configuration's identity.
    """
    file = tmp_path / "compiled-configuration.json"
    file.write_bytes(_compiled_bytes(entry))
    monkeypatch.setattr(entrypoint, "COMPILED_CONFIGURATION_PATH", str(file))
    monkeypatch.setattr(entrypoint, "_factories", _fail("factory construction"))
    monkeypatch.setattr(entrypoint, "_client", _fail("client construction"))
    monkeypatch.setattr(entrypoint, "_transport", _fail("transport construction"))
    monkeypatch.setattr(entrypoint, "_metadata_fetch", _fail("metadata fetch"))
    monkeypatch.setattr(entrypoint, "_resolve_origin", _fail("origin resolution"))
    monkeypatch.setattr(tempfile, "mkdtemp", _fail("working directory"))
    # A workstation: a profile is set and no container credential provider exists.
    monkeypatch.setenv("AWS_PROFILE", "synthetic-profile")
    monkeypatch.delenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", raising=False)
    monkeypatch.delenv("AWS_CONTAINER_CREDENTIALS_FULL_URI", raising=False)
    code = entrypoint.main([entry.value])
    assert code == EXIT_STATUS[TaskOutcome.REFUSED_CREDENTIAL_ENVIRONMENT] == 4
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == task_sentence(TaskOutcome.REFUSED_CREDENTIAL_ENVIRONMENT)
    assert "counts_observed=true" in lines and "s3_operations=0" in lines
    assert lines[-1].startswith("receipt: ") and '"binding_digest":null' in lines[-1]
    document = pr.decode_receipt_line(lines[-1])
    assert document["code_commit"] == COMMIT
    assert document["configuration_digest"] == hashlib.sha256(file.read_bytes()).hexdigest()
    assert "synthetic-profile" not in "\n".join(lines)


def _task_shaped_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The credential environment of a task: the container relative URI and no profile."""
    for name in ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("AWS_CONTAINER_CREDENTIALS_FULL_URI", raising=False)
    monkeypatch.setenv(
        "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
        "/v2/credentials/0f0f0f0f-0f0f-4f0f-8f0f-0f0f0f0f0f0f",
    )


@pytest.mark.parametrize("entry", list(TaskEntry))
def test_an_unusable_working_root_is_refused_before_any_client(
    entry: TaskEntry,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The working directory lives under the task definitions' tmpfs (``/work``) and
    nowhere else. The accepted entrypoint asked the interpreter for its default temporary
    location and, under the task's read-only root with no ``/tmp``, died in ``mkdtemp``
    with a traceback and no receipt; an unusable root is now ``REFUSED_DEPENDENCY``."""
    file = tmp_path / "compiled-configuration.json"
    file.write_bytes(_compiled_bytes(entry))
    monkeypatch.setattr(entrypoint, "COMPILED_CONFIGURATION_PATH", str(file))
    monkeypatch.setattr(entrypoint, "TASK_WORKING_ROOT", str(tmp_path / "absent-work"))
    monkeypatch.setattr(entrypoint, "_factories", _fail("factory construction"))
    monkeypatch.setattr(entrypoint, "_client", _fail("client construction"))
    _task_shaped_environment(monkeypatch)
    code = entrypoint.main([entry.value])
    assert code == EXIT_STATUS[TaskOutcome.REFUSED_DEPENDENCY] == 6
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == task_sentence(TaskOutcome.REFUSED_DEPENDENCY)
    assert "counts_observed=true" in lines and "s3_operations=0" in lines
    document = pr.decode_receipt_line(lines[-1])
    assert document["outcome"] == "REFUSED_DEPENDENCY" and document["code_commit"] == COMMIT
    assert not (tmp_path / "absent-work").exists()  # nothing was created anywhere


@pytest.mark.parametrize("entry", list(TaskEntry))
def test_the_working_directory_is_created_under_the_working_root_and_deleted_before_exit(
    entry: TaskEntry,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """With a usable root the directory is created inside it; whatever the outcome, it is
    gone before exit and the receipt's cleanup accounting is empty."""
    file = tmp_path / "compiled-configuration.json"
    file.write_bytes(_compiled_bytes(entry))
    root = tmp_path / "work"
    root.mkdir()
    monkeypatch.setattr(entrypoint, "COMPILED_CONFIGURATION_PATH", str(file))
    monkeypatch.setattr(entrypoint, "TASK_WORKING_ROOT", str(root))
    created: list[Path] = []
    real_factories = entrypoint._factories

    def observing_factories(entry_: Any, working_directory: Any, **kwargs: Any) -> Any:
        path = Path(working_directory)
        assert path.parent == root and path.name.startswith("kalpamani-task-")
        assert path.is_dir()
        created.append(path)
        return real_factories(entry_, working_directory, **kwargs)

    monkeypatch.setattr(entrypoint, "_factories", observing_factories)
    # Every construction refuses, so the entry stops at REFUSED_DEPENDENCY with the
    # directory already created -- exactly the path on which cleanup must still run.
    monkeypatch.setattr(entrypoint, "_client", _fail("client construction"))
    monkeypatch.setattr(entrypoint, "_transport", _fail("transport construction"))
    monkeypatch.setattr(entrypoint, "_metadata_fetch", _fail("metadata fetch"))
    monkeypatch.setattr(entrypoint, "_resolve_origin", lambda host: sorted(ORIGIN_ADDRESSES))
    _task_shaped_environment(monkeypatch)
    code = entrypoint.main([entry.value])
    assert code == EXIT_STATUS[TaskOutcome.REFUSED_DEPENDENCY] == 6
    assert len(created) == 1 and not created[0].exists()
    assert root.exists() and not any(root.iterdir())
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == task_sentence(TaskOutcome.REFUSED_DEPENDENCY)
    assert not any(line.startswith("cleanup_failure=") for line in lines)
    assert pr.decode_receipt_line(lines[-1])["cleanup_failures"] == []


def test_the_working_root_is_the_task_definitions_tmpfs() -> None:
    compute = (REPO_ROOT / "infra/aws/research-data-plane/production_compute.tf").read_text(
        encoding="utf-8"
    )
    assert entrypoint.TASK_WORKING_ROOT == "/work"
    assert compute.count('containerPath = "/work"') == 2
    assert compute.count("readonlyRootFilesystem = true") == 2
    assert "dir=TASK_WORKING_ROOT" in EXECUTABLE and "mkdtemp(" in EXECUTABLE
    assert EXECUTABLE.count("mkdtemp(") == 1


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
