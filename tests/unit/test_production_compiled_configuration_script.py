"""The compiled-configuration generator: deterministic, strict, value-free (ADR-0044 §6).

Driven through the script's ``generate`` against synthetic inputs in a temporary git
repository, so the clean-tree rule and the recorded commit are exercised without touching
this checkout. Nothing here contacts a registry, a container engine, AWS or a provider.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Final

import pytest

from fixtures.production_build import configuration
from fixtures.production_entry import ORIGIN_ADDRESSES
from kalpamani.data.production.sharadar.compiled import parse_compiled_configuration
from kalpamani.data.production.sharadar.entry import (
    PROBE_ENTRIES,
    TaskEntry,
)

pytestmark = pytest.mark.unit

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
SCRIPT: Final = REPO_ROOT / "scripts" / "production_compiled_configuration.py"
GENERATED_AT: Final = "2026-09-20T00:00:00+00:00"


def _module() -> Any:
    spec = importlib.util.spec_from_file_location("production_compiled_configuration", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generator = _module()


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    """A throwaway git repository with one commit, so code identity is real and clean."""
    git = shutil.which("git")
    if git is None:  # pragma: no cover - the repository's own tests need git
        pytest.skip("git is not available")
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run([git, "init", "-q"], cwd=root, check=True)  # noqa: S603
    subprocess.run(  # noqa: S603
        [
            git,
            "-c",
            "user.name=synthetic",
            "-c",
            "user.email=synthetic@example.invalid",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "synthetic",
        ],
        cwd=root,
        check=True,
    )
    return root


def _inputs(tmp_path: Path, entry: TaskEntry, **overrides: Any) -> Path:
    if entry is TaskEntry.ACQUISITION:
        document: dict[str, Any] = {
            "secret_name": "synthetic/production/sharadar",
            "origin_addresses": sorted(ORIGIN_ADDRESSES),
        }
    elif entry is TaskEntry.BUILD:
        document = {"build_configuration": configuration().document()}
    elif entry in PROBE_ENTRIES:
        # A probe entry (ADR-0048) compiles nothing beyond the code identity.
        document = {}
    else:
        # A verification entry (ADR-0045) compiles the origin set and nothing else.
        document = {"origin_addresses": sorted(ORIGIN_ADDRESSES)}
    document.update(overrides)
    path = tmp_path / "inputs.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


@pytest.mark.parametrize("entry", list(TaskEntry))
def test_generation_is_deterministic_and_records_the_digest(
    entry: TaskEntry, repository: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inputs = _inputs(tmp_path, entry)
    first = tmp_path / "out1"
    second = tmp_path / "out2"
    for output in (first, second):
        code = generator.generate(
            entry_token=entry.value,
            inputs_path=inputs,
            generated_at=GENERATED_AT,
            output=output,
            repository=repository,
        )
        assert code == 0
    raw = (first / "compiled-configuration.json").read_bytes()
    assert raw == (second / "compiled-configuration.json").read_bytes()
    configured, digest = parse_compiled_configuration(raw)
    assert configured.entry is entry
    assert (first / "compiled-configuration.sha256").read_text().strip() == digest
    record = json.loads((first / "generation-record.json").read_text())
    assert record["configuration_digest"] == digest and record["entry"] == entry.value
    assert record["code_commit"] == configured.compiled.code_commit
    assert len(record["code_commit"]) == 40 and record["configuration_bytes"] == len(raw)
    out = capsys.readouterr().out
    assert digest in out and "synthetic/production/sharadar" not in out
    for address in ORIGIN_ADDRESSES:
        assert address not in out


def test_a_dirty_tree_refuses(repository: Path, tmp_path: Path) -> None:
    tracked = repository / "tracked.txt"
    tracked.write_text("x", encoding="utf-8")
    git = shutil.which("git")
    assert git is not None
    subprocess.run([git, "add", "tracked.txt"], cwd=repository, check=True)  # noqa: S603
    code = generator.generate(
        entry_token=TaskEntry.ACQUISITION.value,
        inputs_path=_inputs(tmp_path, TaskEntry.ACQUISITION),
        generated_at=GENERATED_AT,
        output=tmp_path / "out",
        repository=repository,
    )
    assert code == 1 and not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "overrides",
    [
        {"secret_value": "synthetic"},
        {"api_key": "synthetic"},
        {"secret_arn": "arn:aws:secretsmanager:us-east-1:000000000000:secret:x"},
        {"secret_name": "arn:aws:secretsmanager:us-east-1:000000000000:secret:x"},
        {"origin_addresses": []},
        {"origin_addresses": ["::1"]},
        {"extra": 1},
    ],
    ids=["secret-value", "api-key", "secret-arn", "arn-as-name", "no-origin", "ipv6", "extra"],
)
def test_forbidden_or_malformed_inputs_refuse_without_writing(
    overrides: dict[str, Any], repository: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = generator.generate(
        entry_token=TaskEntry.ACQUISITION.value,
        inputs_path=_inputs(tmp_path, TaskEntry.ACQUISITION, **overrides),
        generated_at=GENERATED_AT,
        output=tmp_path / "out",
        repository=repository,
    )
    assert code == 1 and not (tmp_path / "out").exists()
    assert "synthetic" not in capsys.readouterr().out.replace("compiled configuration", "")


def test_a_naive_instant_an_unknown_entry_and_a_missing_file_refuse(
    repository: Path, tmp_path: Path
) -> None:
    inputs = _inputs(tmp_path, TaskEntry.BUILD)
    kwargs: dict[str, Any] = {
        "inputs_path": inputs,
        "generated_at": GENERATED_AT,
        "output": tmp_path / "out",
        "repository": repository,
    }
    assert generator.generate(entry_token="acquire", **kwargs) == 1  # noqa: S106 - a token
    assert (
        generator.generate(
            **{
                **kwargs,
                "entry_token": TaskEntry.BUILD.value,
                "generated_at": "2026-09-20T00:00:00",
            }
        )
        == 1
    )
    assert (
        generator.generate(
            **{
                **kwargs,
                "entry_token": TaskEntry.BUILD.value,
                "inputs_path": tmp_path / "absent.json",
            }
        )
        == 1
    )
    assert not (tmp_path / "out").exists()


def test_the_cli_takes_exactly_four_required_options() -> None:
    parser = generator.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--entry", "x"])
    names = {action.dest for action in parser._actions if action.dest != "help"}
    assert names == {"entry", "inputs", "generated_at", "output"}


def test_the_packaging_files_wire_the_four_entries_and_nothing_else() -> None:
    dockerfile = (REPO_ROOT / "docker" / "production" / "Dockerfile").read_text(encoding="utf-8")
    assert "ARG BASE_IMAGE_DIGEST\nFROM python:3.11-slim@${BASE_IMAGE_DIGEST}" in dockerfile
    assert "ARG KALPAMANI_COMMIT" in dockerfile and "sha256:" not in dockerfile.replace(
        "sha256:<64 hex>", ""
    )
    for entry in TaskEntry:
        assert f'CMD ["{entry.value}"]' in dockerfile
        wrapper = (REPO_ROOT / "docker" / "production" / "entry" / entry.value).read_text(
            encoding="utf-8"
        )
        assert f"production_task_entrypoint.py {entry.value}" in wrapper
    assert "compiled-configuration.json /etc/kalpamani/compiled-configuration.json" in dockerfile
    assert "ENTRYPOINT" not in dockerfile
    # The runtime user is the task definitions' numeric identity, in the image as well:
    # the container runs as that number whatever the image says, so the image says it.
    compute = (REPO_ROOT / "infra/aws/research-data-plane/production_compute.tf").read_text(
        encoding="utf-8"
    )
    # Two production task definitions, two verification ones (ADR-0045) and, under the
    # ADR-0048 declaration, two permission-probe ones; the Dockerfile has one
    # target per entry.
    assert compute.count('user      = "10001:10001"') == len(TaskEntry) == 6
    assert dockerfile.count("USER 10001:10001") == len(TaskEntry)
    assert "USER kalpamani" not in dockerfile
    assert "groupadd --system --gid 10001 kalpamani" in dockerfile
    assert "useradd --system --uid 10001 --gid 10001" in dockerfile
    # The configuration directory is created traversable before the 0444 file is copied
    # into it; the working root is the task definitions' tmpfs path; the build backend
    # comes from the pinned base, never from an unpinned fetch during the wheel build.
    assert "mkdir --mode=0555 /etc/kalpamani" in dockerfile
    assert "mkdir --mode=1777 /work" in dockerfile and "chown 10001:10001 /work" not in dockerfile
    assert "pip install --no-deps --no-build-isolation ." in dockerfile
    assert dockerfile.count("pip install --no-deps --no-build-isolation .") == 1
    assert "BUILD_BACKEND" in dockerfile
    # Six targets (ADR-0045's four, plus ADR-0048's two probe targets): every
    # one traverses its configuration directory and holds its entry executable to a
    # POSIX shebang.
    assert dockerfile.count('mode("/etc/kalpamani") & 0o055 != 0o055') == 6
    assert dockerfile.count('startswith(b"#!/bin/sh\\n")') == 6
    ignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert ignore[0].startswith("#") and "*" in ignore
    admitted = [line[1:] for line in ignore if line.startswith("!")]
    assert "tests/" not in admitted and "docs/" not in admitted and "infra/" not in admitted
    assert "src/" in admitted and "scripts/production_task_entrypoint.py" in admitted
    constraints = (REPO_ROOT / "docker" / "production" / "constraints.txt").read_text(
        encoding="utf-8"
    )
    assert "boto3==1.43.83" in constraints and "botocore==1.43.83" in constraints
    assert "docker/production/build/" in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    # The staging directory may exist on a workstation that followed the procedure; it is
    # git-ignored, so nothing under it is tracked.
    import shutil
    import subprocess

    git = shutil.which("git")
    if git is None:  # pragma: no cover - the repository's own tests need git
        pytest.skip("git is not available")
    tracked = subprocess.run(  # noqa: S603
        [git, "ls-files", "--", "docker/production/build"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert tracked.strip() == ""
