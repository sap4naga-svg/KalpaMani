"""The build-context preparer: source bytes from the exact Git tree, configuration bound.

Driven through the script's ``prepare`` against a throwaway git repository whose
allowlisted image paths carry synthetic content, so the property the packaging trust
chain rests on is inspected directly: **the context holds exactly the tracked files of
the recorded commit and nothing the checkout happens to contain**, and the compiled
configuration beside them agrees with that commit on every recorded identity. The
context's contents are listed from disk; no container engine is invoked, and nothing
here contacts a registry, AWS or a provider.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Final

import pytest

from fixtures.production_entry import ORIGIN_ADDRESSES
from kalpamani.data.production.sharadar.entry import TaskEntry

pytestmark = pytest.mark.unit

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
SCRIPT: Final = REPO_ROOT / "scripts" / "production_build_context.py"
GENERATOR: Final = REPO_ROOT / "scripts" / "production_compiled_configuration.py"
GENERATED_AT: Final = "2026-09-20T00:00:00+00:00"
ACQUIRE: Final = TaskEntry.ACQUISITION.value


def _module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


context = _module("production_build_context", SCRIPT)
generator = _module("production_compiled_configuration", GENERATOR)

#: The synthetic image source tree: one file under every allowlisted path, plus files
#: outside the allowlist that must never be archived.
SOURCE_FILES: Final[dict[str, str]] = {
    "pyproject.toml": "[project]\nname = 'synthetic'\nversion = '0'\n",
    "src/kalpamani/__init__.py": "# baseline\n",
    "src/kalpamani/data/__init__.py": "# baseline data\n",
    "scripts/production_task_entrypoint.py": "# entry\n",
    "docker/production/Dockerfile": "# synthetic dockerfile\n",
    "docker/production/constraints.txt": "boto3==0.0.0\n",
    "docker/production/entry/kalpamani-production-acquire": "#!/bin/sh\n",
    "docker/production/entry/kalpamani-research-build": "#!/bin/sh\n",
}
OUTSIDE_FILES: Final[dict[str, str]] = {
    "tests/unit/test_x.py": "# never in an image\n",
    "docs/x.md": "# never in an image\n",
    "scripts/other_script.py": "# never in an image\n",
    ".gitignore": "docker/production/build/\nsrc/kalpamani/*.local.py\n",
}


class Repository:
    """A throwaway git repository with real commits, driven by a fixed identity."""

    def __init__(self, root: Path) -> None:
        self.root = root
        git = shutil.which("git")
        if git is None:  # pragma: no cover - the repository's own tests need git
            pytest.skip("git is not available")
        self.git: str = git
        root.mkdir()
        self("init", "-q")

    def __call__(self, *arguments: str) -> str:
        completed = subprocess.run(  # noqa: S603
            [
                self.git,
                "-c",
                "user.name=synthetic",
                "-c",
                "user.email=synthetic@example.invalid",
                "-c",
                "core.autocrlf=false",
                *arguments,
            ],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        )
        return str(completed.stdout).strip()

    def write(self, files: dict[str, str]) -> None:
        """Write the bytes exactly: ``write_text`` would translate LF to the platform's."""
        for name, content in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode("utf-8"))

    def commit(self, message: str) -> str:
        self("add", "-A")
        self("commit", "-q", "-m", message)
        return self("rev-parse", "HEAD")

    def tree(self, commit: str) -> str:
        return self("rev-parse", commit + "^{tree}")

    def tracked_sources(self, commit: str) -> list[str]:
        listing = self("ls-tree", "-r", "--name-only", commit, "--", *context.IMAGE_SOURCE_PATHS)
        return sorted(line for line in listing.splitlines() if line)


@pytest.fixture
def repository(tmp_path: Path) -> Repository:
    repo = Repository(tmp_path / "repo")
    repo.write(SOURCE_FILES)
    repo.write(OUTSIDE_FILES)
    repo.commit("baseline")
    return repo


def _generate(repo: Repository, tmp_path: Path, entry: str = ACQUIRE) -> Path:
    """The generator's staging directory for ``entry``, produced at the checkout's HEAD."""
    inputs = tmp_path / f"{entry}-inputs.json"
    if entry == ACQUIRE:
        document: dict[str, Any] = {
            "secret_name": "synthetic/production/sharadar",
            "origin_addresses": sorted(ORIGIN_ADDRESSES),
        }
    else:
        from fixtures.production_build import configuration

        document = {"build_configuration": configuration().document()}
    inputs.write_text(json.dumps(document), encoding="utf-8")
    output = repo.root / "docker" / "production" / "build" / entry
    assert (
        generator.generate(
            entry_token=entry,
            inputs_path=inputs,
            generated_at=GENERATED_AT,
            output=output,
            repository=repo.root,
        )
        == 0
    )
    return output


def _context_files(output: Path) -> list[str]:
    return sorted(
        str(path.relative_to(output)).replace("\\", "/")
        for path in output.rglob("*")
        if path.is_file()
    )


def _prepare(
    repo: Repository, staging: Path, output: Path, commit: str, entry: str = ACQUIRE
) -> int:
    return int(
        context.prepare(
            entry_token=entry,
            commit=commit,
            configuration=staging,
            output=output,
            repository=repo.root,
        )
    )


# ---------------------------------------------------------------------------
# Finding 1: the context is the tree, not the checkout
# ---------------------------------------------------------------------------


def test_the_context_holds_exactly_the_tracked_sources_and_the_declared_configuration(
    repository: Repository, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    commit = repository("rev-parse", "HEAD")
    staging = _generate(repository, tmp_path)
    output = tmp_path / "context"
    assert _prepare(repository, staging, output, commit) == 0
    files = _context_files(output)
    sources = [
        f for f in files if f not in (context.CONTEXT_CONFIGURATION_PATH, "context-manifest.json")
    ]
    assert sources == repository.tracked_sources(commit) == sorted(SOURCE_FILES)
    assert not any(name in files for name in OUTSIDE_FILES)
    # Byte-for-byte the committed content.
    for name, content in SOURCE_FILES.items():
        assert (output / name).read_text(encoding="utf-8") == content
    # The configuration is the generator's exact bytes, under the declared input path --
    # never under a path that would present it as part of the source tree.
    assert (output / context.CONTEXT_CONFIGURATION_PATH).read_bytes() == (
        staging / "compiled-configuration.json"
    ).read_bytes()
    assert not (output / "docker" / "production" / "build").exists()
    manifest = json.loads((output / "context-manifest.json").read_text(encoding="utf-8"))
    record = json.loads((staging / "generation-record.json").read_text(encoding="utf-8"))
    assert manifest["code_commit"] == commit == record["code_commit"]
    assert manifest["code_tree"] == repository.tree(commit) == record["code_tree"]
    assert manifest["configuration_digest"] == record["configuration_digest"]
    assert manifest["source_files"] == len(SOURCE_FILES)
    assert manifest["build_arguments"] == {
        "KALPAMANI_COMMIT": commit,
        "CONFIGURATION_DIGEST": record["configuration_digest"],
    }
    out = capsys.readouterr().out
    assert f"code_commit={commit}" in out and "synthetic/production" not in out
    assert "198." not in out and "192." not in out  # no origin address is printed


def test_an_untracked_module_under_an_admitted_path_never_reaches_the_context(
    repository: Repository, tmp_path: Path
) -> None:
    """The reproduction of the finding: the generator accepted this checkout, and a COPY
    of the working tree would have shipped the extra module; the context does not."""
    commit = repository("rev-parse", "HEAD")
    staging = _generate(repository, tmp_path)
    extra = repository.root / "src" / "kalpamani" / "smuggled.py"
    extra.write_text("print('not in any commit')\n", encoding="utf-8")
    assert "?? src/kalpamani/smuggled.py" in repository("status", "--porcelain")
    # The generator's clean-tree rule ignores untracked files -- which is exactly why
    # the checkout can never be the context.
    assert repository("status", "--porcelain", "--untracked-files=no") == ""
    output = tmp_path / "context"
    assert _prepare(repository, staging, output, commit) == 0
    files = _context_files(output)
    assert "src/kalpamani/smuggled.py" not in files
    assert [f for f in files if f.startswith("src/")] == sorted(
        f for f in SOURCE_FILES if f.startswith("src/")
    )


def test_an_ignored_file_under_an_admitted_path_never_reaches_the_context(
    repository: Repository, tmp_path: Path
) -> None:
    """Docker's COPY honours .dockerignore, not .gitignore: an ignored file in the
    checkout is invisible to git status and would still be copied from a working tree."""
    commit = repository("rev-parse", "HEAD")
    staging = _generate(repository, tmp_path)
    ignored = repository.root / "src" / "kalpamani" / "secrets.local.py"
    ignored.write_text("TOKEN = 'never'\n", encoding="utf-8")
    assert repository("status", "--porcelain") == ""  # ignored: invisible to status
    output = tmp_path / "context"
    assert _prepare(repository, staging, output, commit) == 0
    assert "src/kalpamani/secrets.local.py" not in _context_files(output)


def test_a_modified_tracked_source_never_reaches_the_context(
    repository: Repository, tmp_path: Path
) -> None:
    """The committed bytes are archived, whatever the working tree holds now."""
    commit = repository("rev-parse", "HEAD")
    staging = _generate(repository, tmp_path)
    modified = repository.root / "src" / "kalpamani" / "__init__.py"
    modified.write_text("# modified after generation\n", encoding="utf-8")
    assert "M src/kalpamani/__init__.py" in repository("status", "--porcelain")
    output = tmp_path / "context"
    assert _prepare(repository, staging, output, commit) == 0
    assert (output / "src/kalpamani/__init__.py").read_text(encoding="utf-8") == "# baseline\n"


def test_a_deleted_tracked_source_is_restored_from_the_tree(
    repository: Repository, tmp_path: Path
) -> None:
    commit = repository("rev-parse", "HEAD")
    staging = _generate(repository, tmp_path)
    (repository.root / "src" / "kalpamani" / "data" / "__init__.py").unlink()
    output = tmp_path / "context"
    assert _prepare(repository, staging, output, commit) == 0
    assert "src/kalpamani/data/__init__.py" in _context_files(output)


def test_preparation_is_deterministic(repository: Repository, tmp_path: Path) -> None:
    commit = repository("rev-parse", "HEAD")
    staging = _generate(repository, tmp_path)
    manifests = []
    for name in ("one", "two"):
        output = tmp_path / name
        assert _prepare(repository, staging, output, commit) == 0
        manifests.append((output / "context-manifest.json").read_bytes())
        assert _context_files(output) == _context_files(tmp_path / "one")
    assert manifests[0] == manifests[1]


# ---------------------------------------------------------------------------
# Finding 2 (image-verification cycle): the bytes are the blobs', on any workstation
# ---------------------------------------------------------------------------


def _write_bytes(repo: Repository, name: str, content: bytes) -> None:
    path = repo.root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _crlf_workstation(repo: Repository) -> None:
    """What a Windows checkout of this repository looks like to ``git archive``.

    The repository's own ``.gitattributes`` normalizes text (``* text=auto``) and the
    workstation checks out native line endings (``core.autocrlf=true``); the setting is
    written into the throwaway repository's configuration so that the preparer's own git
    invocation -- not the fixture's ``-c core.autocrlf=false`` -- sees it.
    """
    repo.write({".gitattributes": "* text=auto\n"})
    repo.commit("attributes")
    repo("config", "core.autocrlf", "true")


def test_the_context_carries_the_blob_bytes_on_a_crlf_workstation(
    repository: Repository, tmp_path: Path
) -> None:
    """The defect the first local image build demonstrated: ``git archive`` on a Windows
    checkout emitted CRLF into the POSIX entry executables, whose ``#!/bin/sh\\r``
    shebang then no longer executed inside the container, and the source digest
    depended on the workstation. The context must carry the tree's bytes exactly."""
    _crlf_workstation(repository)
    commit = repository("rev-parse", "HEAD")
    # The workstation's own archive would carry CRLF here; the preparer must not.
    raw = subprocess.run(  # noqa: S603
        [repository.git, "archive", "--format=tar", commit, "--", "docker/production/entry"],
        cwd=repository.root,
        check=True,
        capture_output=True,
    ).stdout
    assert b"#!/bin/sh\r\n" in raw, "the fixture did not reproduce a CRLF workstation"
    staging = _generate(repository, tmp_path)
    output = tmp_path / "context"
    assert _prepare(repository, staging, output, commit) == 0
    for name, content in SOURCE_FILES.items():
        assert (output / name).read_bytes() == content.encode("utf-8"), name
    entry = (output / "docker/production/entry/kalpamani-production-acquire").read_bytes()
    assert entry.startswith(b"#!/bin/sh\n") and b"\r" not in entry


def test_the_source_digest_is_the_trees_whatever_the_workstation_converts(
    tmp_path: Path,
) -> None:
    """Two checkouts of the same tree -- one converting line endings, one not -- prepare
    contexts with the same source digest, because the digest is over the blobs."""
    digests = []
    for name, convert in (("plain", False), ("crlf", True)):
        repo = Repository(tmp_path / name)
        repo.write(SOURCE_FILES)
        repo.write(OUTSIDE_FILES)
        repo.commit("baseline")
        if convert:
            _crlf_workstation(repo)
        else:
            repo("config", "core.autocrlf", "false")  # not the workstation's global setting
        commit = repo("rev-parse", "HEAD")
        (tmp_path / f"{name}-staging").mkdir()
        staging = _generate(repo, tmp_path / f"{name}-staging")
        output = tmp_path / f"{name}-context"
        assert _prepare(repo, staging, output, commit) == 0
        manifest = json.loads((output / "context-manifest.json").read_text(encoding="utf-8"))
        digests.append(manifest["source_digest"])
    assert digests[0] == digests[1]


def test_the_manifest_names_the_executable_sources_the_tree_marks(
    repository: Repository, tmp_path: Path
) -> None:
    for name in (
        "docker/production/entry/kalpamani-production-acquire",
        "docker/production/entry/kalpamani-research-build",
    ):
        repository("update-index", "--chmod=+x", name)
    repository("commit", "-q", "-m", "executable entries")
    commit = repository("rev-parse", "HEAD")
    staging = _generate(repository, tmp_path)
    output = tmp_path / "context"
    assert _prepare(repository, staging, output, commit) == 0
    manifest = json.loads((output / "context-manifest.json").read_text(encoding="utf-8"))
    assert manifest["executable_sources"] == [
        "docker/production/entry/kalpamani-production-acquire",
        "docker/production/entry/kalpamani-research-build",
    ]


def test_an_archive_whose_bytes_are_not_the_blobs_is_refused(
    repository: Repository, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``export-subst`` makes ``git archive`` rewrite a file's content at archive time,
    so the extracted bytes are no longer the tree's blob: the preparer must refuse
    rather than record a digest over bytes the commit does not hold."""
    repository.write(
        {
            ".gitattributes": "src/kalpamani/marker.py export-subst\n",
            "src/kalpamani/marker.py": "# $Format:%H$\n",
        }
    )
    commit = repository.commit("substituted")
    staging = _generate(repository, tmp_path)
    _refuses(
        repository,
        staging,
        tmp_path / "context",
        commit,
        capsys,
        reason="could not be archived byte-exactly",
    )


def test_a_symbolic_link_under_an_admitted_path_is_refused(
    repository: Repository, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A link is written into the index directly (mode 120000), so the test needs no
    filesystem symlink support; the tree then carries something an image may not."""
    object_id = (
        subprocess.run(  # noqa: S603
            [repository.git, "hash-object", "-w", "--stdin"],
            cwd=repository.root,
            check=True,
            capture_output=True,
            input=b"../../etc/passwd",
        )
        .stdout.decode()
        .strip()
    )
    repository("update-index", "--add", "--cacheinfo", f"120000,{object_id},src/kalpamani/link")
    repository("commit", "-q", "-m", "link")
    repository("reset", "-q", "--hard")  # materialize the checkout so the generator sees it clean
    commit = repository("rev-parse", "HEAD")
    staging = _generate(repository, tmp_path)
    _refuses(
        repository,
        staging,
        tmp_path / "context",
        commit,
        capsys,
        reason="could not be archived byte-exactly",
    )


# ---------------------------------------------------------------------------
# Disagreement is refused, never relabelled
# ---------------------------------------------------------------------------


def _refuses(
    repo: Repository, staging: Path, output: Path, commit: str, capsys: Any, *, reason: str
) -> None:
    capsys.readouterr()  # the generator's own two lines
    assert _prepare(repo, staging, output, commit) == 1
    out = capsys.readouterr().out
    assert out.startswith("build context refused: ") and reason in out, out
    assert len(out.splitlines()) == 1  # one sentence; no digest, no path, no value
    assert not output.exists()


def test_a_configuration_generated_at_an_earlier_commit_is_stale_for_a_later_one(
    repository: Repository, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Generated at commit 1, a new commit made: the record names commit 1, so preparing
    commit 2 with it is refused rather than relabelled -- and preparing commit 1 still
    works, because commit 1's tree is what the record binds."""
    first = repository("rev-parse", "HEAD")
    staging = _generate(repository, tmp_path)
    repository.write({"src/kalpamani/later.py": "# a later change\n"})
    second = repository.commit("later")
    assert first != second
    _refuses(repository, staging, tmp_path / "ctx2", second, capsys, reason="another commit")
    output = tmp_path / "ctx1"
    assert _prepare(repository, staging, output, first) == 0
    assert "src/kalpamani/later.py" not in _context_files(output)


def test_a_record_naming_the_right_commit_but_another_tree_is_refused(
    repository: Repository, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    commit = repository("rev-parse", "HEAD")
    staging = _generate(repository, tmp_path)
    record_path = staging / "generation-record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["code_tree"] = "0" * 40
    record_path.write_text(json.dumps(record), encoding="utf-8")
    _refuses(repository, staging, tmp_path / "ctx", commit, capsys, reason="another tree")


def test_a_tampered_configuration_file_is_refused(
    repository: Repository, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    commit = repository("rev-parse", "HEAD")
    staging = _generate(repository, tmp_path)
    file = staging / "compiled-configuration.json"
    file.write_bytes(file.read_bytes().replace(b'"schema_version":1', b'"schema_version":1 '))
    _refuses(repository, staging, tmp_path / "ctx", commit, capsys, reason="recorded digest")


def test_a_record_and_sidecar_rewritten_to_a_tampered_file_still_disagree_with_its_contents(
    repository: Repository, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Even a consistent forgery of record + sidecar + file is refused when the file's
    own code identity is not the commit's: the contents are parsed, not just hashed."""
    import hashlib

    commit = repository("rev-parse", "HEAD")
    staging = _generate(repository, tmp_path)
    file = staging / "compiled-configuration.json"
    document = json.loads(file.read_bytes())
    document["code_commit"] = "1" * 40
    from kalpamani.data.contracts.canonical import canonical_bytes

    raw = canonical_bytes(document)
    file.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    (staging / "compiled-configuration.sha256").write_text(digest + "\n", encoding="utf-8")
    record_path = staging / "generation-record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["configuration_digest"] = digest
    record["configuration_bytes"] = len(raw)
    record_path.write_text(json.dumps(record), encoding="utf-8")
    _refuses(repository, staging, tmp_path / "ctx", commit, capsys, reason="another code identity")


def test_a_sidecar_digest_that_disagrees_is_refused(
    repository: Repository, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    commit = repository("rev-parse", "HEAD")
    staging = _generate(repository, tmp_path)
    (staging / "compiled-configuration.sha256").write_text("f" * 64 + "\n", encoding="utf-8")
    _refuses(repository, staging, tmp_path / "ctx", commit, capsys, reason="recorded digest")


def test_a_configuration_for_the_other_entry_is_refused(
    repository: Repository, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    commit = repository("rev-parse", "HEAD")
    staging = _generate(repository, tmp_path, entry=TaskEntry.BUILD.value)
    _refuses(repository, staging, tmp_path / "ctx", commit, capsys, reason="another entry")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.unlink(),
        lambda p: p.write_text("{", encoding="utf-8"),
        lambda p: p.write_text('{"entry":"x","entry":"y"}', encoding="utf-8"),
        lambda p: p.write_text(json.dumps({"code_commit": "x"}), encoding="utf-8"),
        lambda p: p.write_bytes(b"{" + b" " * 5000 + b"}"),
    ],
    ids=["absent", "not-json", "duplicate-key", "missing-fields", "oversize"],
)
def test_a_record_that_is_not_the_closed_record_is_refused(
    mutate: Any, repository: Repository, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    commit = repository("rev-parse", "HEAD")
    staging = _generate(repository, tmp_path)
    mutate(staging / "generation-record.json")
    _refuses(repository, staging, tmp_path / "ctx", commit, capsys, reason="generation record")


@pytest.mark.parametrize(
    "commit_argument",
    ["HEAD", "main", "abc123", "0" * 40, "A" * 40, "", "HEAD^{commit}"],
)
def test_anything_but_the_exact_full_commit_id_is_refused(
    commit_argument: str,
    repository: Repository,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    staging = _generate(repository, tmp_path)
    _refuses(
        repository, staging, tmp_path / "ctx", commit_argument, capsys, reason="full commit id"
    )


def test_an_existing_output_and_an_output_inside_the_repository_are_refused(
    repository: Repository, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    commit = repository("rev-parse", "HEAD")
    staging = _generate(repository, tmp_path)
    existing = tmp_path / "ctx"
    existing.mkdir()
    assert _prepare(repository, staging, existing, commit) == 1
    assert "already exists" in capsys.readouterr().out
    assert _context_files(existing) == []
    inside = repository.root / "context"
    assert _prepare(repository, staging, inside, commit) == 1
    assert "outside the repository" in capsys.readouterr().out
    assert not inside.exists()


def test_an_unknown_entry_refuses_before_git_is_consulted(
    repository: Repository, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    staging = _generate(repository, tmp_path)
    assert (
        context.prepare(
            entry_token="acquire",  # noqa: S106 - an entry name, not a secret
            commit="0" * 40,
            configuration=staging,
            output=tmp_path / "ctx",
            repository=repository.root,
        )
        == 1
    )
    assert "closed entries" in capsys.readouterr().out


def test_the_cli_takes_exactly_four_required_options() -> None:
    parser = context.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--entry", "x"])
    names = {action.dest for action in parser._actions if action.dest != "help"}
    assert names == {"entry", "commit", "configuration", "output"}


# ---------------------------------------------------------------------------
# The packaging files match the implemented guarantees
# ---------------------------------------------------------------------------


def test_the_dockerfile_copies_only_the_allowlisted_sources_and_the_declared_configuration() -> (
    None
):
    dockerfile = (REPO_ROOT / "docker" / "production" / "Dockerfile").read_text(encoding="utf-8")
    copied = sorted(
        line.split()[-2] for line in dockerfile.splitlines() if line.startswith("COPY ")
    )
    for source in copied:
        assert source == "configuration/compiled-configuration.json" or any(
            source == path or source.startswith(path + "/") for path in context.IMAGE_SOURCE_PATHS
        ), source
    assert "docker/production/build" not in dockerfile
    # One copy per target: two production, two verification and (ADR-0048)
    # two permission-probe targets.
    assert dockerfile.count("COPY --chmod=0444 configuration/compiled-configuration.json") == 6
    assert dockerfile.count("ARG CONFIGURATION_DIGEST") == 6
    assert (
        dockerfile.count('hashlib.sha256(raw).hexdigest() != os.environ["CONFIGURATION_DIGEST"]')
        == 6
    )
    assert dockerfile.count('document.get("code_commit") != commit') == 6
    # Every refusal is a closed sentence; no clause prints a digest, a commit or a field.
    assert dockerfile.count("image check refused: ") == 6
    for line in dockerfile.splitlines():
        if line.strip().startswith("refuse("):
            assert "{" not in line and "%" not in line and "+" not in line.split("refuse(")[1]
    for entry in TaskEntry:
        assert f"EXPECTED_ENTRY={entry.value} python" in dockerfile
    # The Dockerfile itself is archived from the tree, so a build uses the commit's own.
    assert "docker/production/Dockerfile" in context.IMAGE_SOURCE_PATHS


def test_the_repository_root_dockerignore_admits_no_staging_directory() -> None:
    ignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    admitted = [line[1:] for line in ignore if line.startswith("!")]
    assert not any(path.startswith("docker/production/build") for path in admitted)
    assert not any(path.startswith("configuration") for path in admitted)
    assert "NOT THE PRODUCTION IMAGE BUILD CONTEXT" in ignore[0]


def test_the_procedure_documents_the_prepared_context() -> None:
    procedure = (REPO_ROOT / "docs" / "operations" / "production-image-build.md").read_text(
        encoding="utf-8"
    )
    assert "scripts/production_build_context.py" in procedure
    assert "git archive" in procedure and "CONFIGURATION_DIGEST" in procedure
    assert "context-manifest.json" in procedure
    assert "never the working tree" in procedure or "never a working tree" in procedure
