"""Prepare one production image's build context from the exact Git tree (ADR-0044 §2, §6).

**Run by the owner at the image gate, never by a task and never by CI.** The image's
source bytes come from **the tree of the recorded commit**, never from a working tree:
``git archive <commit>`` over the closed allowlist of image source paths is extracted
into a fresh directory, so an untracked, ignored or locally modified file under an
admitted path -- which ``docker build`` from a checkout would copy without any record
of it -- cannot reach the build. The generated compiled configuration is then placed
beside that source as a **separately declared, digest-bound input**: it is not part of
the commit and is never presented as if it were.

```text
python scripts/production_build_context.py \\
    --entry kalpamani-production-acquire \\
    --commit <40-hex commit> \\
    --configuration docker/production/build/acquire \\
    --output <outside the repository>/kalpamani-context-acquire
```

**What must agree, and is refused otherwise.** The commit argument must resolve to
exactly itself; the generation record must name that commit and its tree; the compiled
configuration file must hash to the record's digest and to the ``.sha256`` beside it,
must parse under the accepted contract for the same entry, and must carry the same
commit and tree inside it. A disagreement is a refusal: nothing is regenerated,
relabelled or written. The resulting directory carries a manifest naming the commit,
the tree, the configuration digest and a digest over every source file, and it is the
**only** build context the documented procedure accepts -- the Dockerfile it contains
copies the configuration from ``configuration/`` and verifies, at build time, that the
file's digest equals the ``CONFIGURATION_DIGEST`` build argument and that its recorded
commit equals ``KALPAMANI_COMMIT``.

**The extracted bytes are the tree's bytes, proven per file.** ``git archive`` honours
the checkout's end-of-line conversion (``core.autocrlf`` and a ``text=auto`` attribute), so
on a Windows workstation it would otherwise emit CRLF into a POSIX shell entry executable
whose shebang then no longer executes, and the source digest would depend on the
workstation rather than the tree. The archive is therefore taken with conversion
disabled, and every extracted regular file is then hashed as a Git blob and held equal
to the object id the commit's own tree lists for that path; a disagreement, a symbolic
link, a submodule or a mode outside a regular file's is a refusal.

**Nothing here contacts AWS, a provider, a registry or a container engine**, and no
value from the configuration is printed: the output is the entry, the commit, the
configuration digest and a file count.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any, Final

#: The image source paths, exactly the ones the Dockerfile copies from the context.
#: Closed: a path outside this tuple is never archived, whatever the checkout holds.
IMAGE_SOURCE_PATHS: Final[tuple[str, ...]] = (
    "pyproject.toml",
    "src",
    "scripts/production_task_entrypoint.py",
    "docker/production/Dockerfile",
    "docker/production/constraints.txt",
    "docker/production/entry",
)
#: Where the context carries the compiled configuration: a declared input, not source.
CONTEXT_CONFIGURATION_PATH: Final = "configuration/compiled-configuration.json"
CONTEXT_MANIFEST_NAME: Final = "context-manifest.json"
#: The generation record is small and closed; anything larger is not one.
MAX_RECORD_BYTES: Final = 4 * 1024
_RECORD_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "entry",
        "code_commit",
        "code_tree",
        "generated_at",
        "configuration_digest",
        "configuration_bytes",
    }
)
_HEX40: Final = re.compile(r"[0-9a-f]{40}")
_HEX64: Final = re.compile(r"[0-9a-f]{64}")

EXIT_OK: Final = 0
EXIT_REFUSED: Final = 1


def _refuse(reason: str) -> int:
    print(f"build context refused: {reason}")
    return EXIT_REFUSED


def _git() -> str | None:
    import shutil

    return shutil.which("git")


def _run(git: str, repository: Path, *arguments: str) -> bytes | None:
    """One git command's stdout, or ``None`` on any failure. Nothing is printed."""
    try:
        completed = subprocess.run(  # noqa: S603 - a fixed argument vector
            [git, *arguments], cwd=repository, capture_output=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return completed.stdout


def resolve_commit(git: str, repository: Path, commit: str) -> tuple[str, str] | None:
    """``(commit, tree)`` when ``commit`` is a full commit id this repository holds.

    An abbreviation, a branch name, a tag or an unknown id is refused: the recorded
    commit must be spelled exactly, so that what is built is what the record names.
    """
    if type(commit) is not str or _HEX40.fullmatch(commit) is None:
        return None
    resolved = _run(git, repository, "rev-parse", "--verify", "--quiet", commit + "^{commit}")
    if resolved is None or resolved.decode("ascii", "replace").strip() != commit:
        return None
    tree = _run(git, repository, "rev-parse", "--verify", "--quiet", commit + "^{tree}")
    if tree is None:
        return None
    tree_id = tree.decode("ascii", "replace").strip()
    if _HEX40.fullmatch(tree_id) is None:
        return None
    return commit, tree_id


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError("duplicate key")
        seen[key] = value
    return seen


def _read_record(path: Path) -> dict[str, Any] | None:
    """The closed generation record, or ``None`` for anything that is not one."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if not raw or len(raw) > MAX_RECORD_BYTES:
        return None
    try:
        record = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicate_keys)
    except (ValueError, RecursionError):
        return None
    if type(record) is not dict or set(record) != _RECORD_FIELDS:
        return None
    return record


def verify_configuration_input(
    *, entry_token: str, commit: str, tree: str, configuration: Path
) -> tuple[bytes, str] | str:
    """The compiled configuration bytes and digest, or the reason they are refused.

    Every recorded identity must agree: the record's entry, commit and tree with the
    arguments and the resolved tree; the record's digest and byte count with the file;
    the ``.sha256`` beside it with the same digest; and the file's own contents, parsed
    under the accepted contract, with the same entry, commit and tree.
    """
    from kalpamani.data.production.sharadar.compiled import (
        MAX_COMPILED_CONFIGURATION_BYTES,
        CompiledConfigurationError,
        decode_compiled_configuration,
        parse_compiled_configuration,
    )

    record = _read_record(configuration / "generation-record.json")
    if record is None:
        return "the generation record is absent or is not the closed record"
    if record["entry"] != entry_token:
        return "the generation record was produced for another entry"
    if record["code_commit"] != commit:
        return "the generation record names another commit"
    if record["code_tree"] != tree:
        return "the generation record names another tree"
    declared = record["configuration_digest"]
    if type(declared) is not str or _HEX64.fullmatch(declared) is None:
        return "the generation record carries no usable configuration digest"
    try:
        raw = (configuration / "compiled-configuration.json").read_bytes()
        sidecar = (configuration / "compiled-configuration.sha256").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "the compiled configuration or its digest file could not be read"
    if not raw or len(raw) > MAX_COMPILED_CONFIGURATION_BYTES:
        return "the compiled configuration is empty or above the ceiling"
    digest = hashlib.sha256(raw).hexdigest()
    if digest != declared or sidecar.strip() != declared:
        return "the compiled configuration does not hash to the recorded digest"
    if record["configuration_bytes"] != len(raw):
        return "the compiled configuration is not the recorded size"
    try:
        parsed, parsed_digest = parse_compiled_configuration(raw)
        document = decode_compiled_configuration(raw)
    except CompiledConfigurationError:
        return "the compiled configuration does not parse under the accepted contract"
    if parsed_digest != digest or parsed.entry.value != entry_token:
        return "the compiled configuration was compiled for another entry"
    if parsed.compiled.code_commit != commit or document.get("code_tree") != tree:
        return "the compiled configuration carries another code identity"
    return raw, digest


#: The two tree entry modes of a regular file. A symbolic link (``120000``) and a
#: submodule (``160000``) are refused: neither is source an image may carry.
_REGULAR_FILE_MODES: Final[frozenset[str]] = frozenset({"100644", "100755"})
_EXECUTABLE_MODE: Final = "100755"

#: The archive is taken with every end-of-line conversion disabled, so the bytes are
#: the blobs' whatever ``core.autocrlf`` or a ``text`` attribute says on this workstation.
_ARCHIVE_OPTIONS: Final[tuple[str, ...]] = (
    "-c",
    "core.autocrlf=false",
    "-c",
    "core.eol=lf",
    "-c",
    "core.safecrlf=false",
)


def _blob_id(content: bytes, object_id: str) -> str:
    """The Git object id of ``content`` as a blob, in the hash the repository uses."""
    algorithm = hashlib.sha256() if len(object_id) == 64 else hashlib.sha1()  # noqa: S324
    algorithm.update(b"blob %d\0" % len(content))
    algorithm.update(content)
    return algorithm.hexdigest()


def _tree_listing(git: str, repository: Path, commit: str) -> dict[str, tuple[str, str]] | None:
    """Every allowlisted path in the commit's tree, to ``(mode, object id)``.

    ``None`` when the listing could not be produced, is empty, or carries anything but
    a regular-file blob.
    """
    listing = _run(git, repository, "ls-tree", "-r", commit, "--", *IMAGE_SOURCE_PATHS)
    if listing is None:
        return None
    expected: dict[str, tuple[str, str]] = {}
    for line in listing.decode("utf-8", "replace").splitlines():
        if not line:
            continue
        meta, separator, path = line.partition("\t")
        parts = meta.split()
        if separator != "\t" or len(parts) != 3 or not path:
            return None
        mode, kind, object_id = parts
        if kind != "blob" or mode not in _REGULAR_FILE_MODES:
            return None
        if _HEX40.fullmatch(object_id) is None and _HEX64.fullmatch(object_id) is None:
            return None
        expected[path] = (mode, object_id)
    return expected or None


def _archive_sources(
    git: str, repository: Path, commit: str, output: Path
) -> tuple[list[str], list[str]] | None:
    """Extract the allowlisted image source paths of ``commit`` into ``output``.

    Returns the extracted regular-file paths and the subset the tree marks executable,
    or ``None`` when the archive could not be produced, carried anything but directories
    and regular files, disagrees with the commit's own listing of those paths, or holds
    any file whose bytes are not the tree's blob for that path.
    """
    listing = _tree_listing(git, repository, commit)
    if listing is None:
        return None
    expected = sorted(listing)
    archive = _run(
        git,
        repository,
        *_ARCHIVE_OPTIONS,
        "archive",
        "--format=tar",
        commit,
        "--",
        *IMAGE_SOURCE_PATHS,
    )
    if archive is None:
        return None
    extracted: list[str] = []
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
            members = tar.getmembers()
            for member in members:
                if member.isdir():
                    continue
                if not member.isreg():
                    return None
                name = member.name
                if name.startswith("/") or ".." in name.split("/"):
                    return None
                if not any(
                    name == path or name.startswith(path + "/") for path in IMAGE_SOURCE_PATHS
                ):
                    return None
                extracted.append(name)
            tar.extractall(output, filter="data")
    except (tarfile.TarError, OSError, ValueError):
        return None
    if sorted(extracted) != expected:
        return None
    for name in extracted:
        object_id = listing[name][1]
        try:
            content = (output / name).read_bytes()
        except OSError:
            return None
        if _blob_id(content, object_id) != object_id:
            return None
    executable = sorted(name for name in extracted if listing[name][0] == _EXECUTABLE_MODE)
    return sorted(extracted), executable


def _source_digest(output: Path, files: list[str]) -> str:
    """One SHA-256 over every source file's path and content, in path order."""
    summary = hashlib.sha256()
    for name in files:
        content = hashlib.sha256((output / name).read_bytes()).hexdigest()
        summary.update(f"{name}\0{content}\n".encode())
    return summary.hexdigest()


def prepare(
    *,
    entry_token: str,
    commit: str,
    configuration: Path,
    output: Path,
    repository: Path,
) -> int:
    """Prepare one build context, or refuse. Returns the exit status."""
    from kalpamani.data.production.sharadar.entry import select_entry

    entry = select_entry([entry_token])
    if entry is None:
        return _refuse("the entry is not one of the two closed entries")
    git = _git()
    if git is None:
        return _refuse("git is not available")
    resolved = resolve_commit(git, repository, commit)
    if resolved is None:
        return _refuse("the commit is not a full commit id this repository holds")
    commit, tree = resolved
    verified = verify_configuration_input(
        entry_token=entry.value, commit=commit, tree=tree, configuration=configuration
    )
    if isinstance(verified, str):
        return _refuse(verified)
    raw, digest = verified
    if output.exists():
        return _refuse("the output directory already exists; a context is prepared fresh")
    try:
        if output.resolve().is_relative_to(repository.resolve()):
            return _refuse("the output directory must lie outside the repository")
    except OSError:
        return _refuse("the output directory could not be resolved")
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError:
        return _refuse("the output directory could not be created")
    archived = _archive_sources(git, repository, commit, output)
    if archived is None:
        _remove(output)
        return _refuse("the source tree could not be archived byte-exactly from the commit")
    files, executable = archived
    target = output / CONTEXT_CONFIGURATION_PATH
    target.parent.mkdir(parents=True, exist_ok=False)
    target.write_bytes(raw)
    manifest: dict[str, Any] = {
        "entry": entry.value,
        "code_commit": commit,
        "code_tree": tree,
        "source_paths": list(IMAGE_SOURCE_PATHS),
        "source_files": len(files),
        "source_digest": _source_digest(output, files),
        "executable_sources": executable,
        "configuration_path": CONTEXT_CONFIGURATION_PATH,
        "configuration_digest": digest,
        "configuration_bytes": len(raw),
        "build_arguments": {"KALPAMANI_COMMIT": commit, "CONFIGURATION_DIGEST": digest},
    }
    (output / CONTEXT_MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"build context prepared: entry={entry.value} source_files={len(files)}")
    print(f"code_commit={commit}")
    print(f"configuration_digest={digest}")
    return EXIT_OK


def _remove(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)


def build_parser() -> argparse.ArgumentParser:
    """Exactly four options; every one required."""
    parser = argparse.ArgumentParser(
        prog="production_build_context", add_help=True, allow_abbrev=False
    )
    parser.add_argument("--entry", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--configuration", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse and prepare. Never prints a configuration value."""
    arguments = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    return prepare(
        entry_token=arguments.entry,
        commit=arguments.commit,
        configuration=Path(arguments.configuration),
        output=Path(arguments.output),
        repository=Path(__file__).resolve().parents[1],
    )


__all__ = [
    "CONTEXT_CONFIGURATION_PATH",
    "CONTEXT_MANIFEST_NAME",
    "IMAGE_SOURCE_PATHS",
    "main",
    "prepare",
    "resolve_commit",
    "verify_configuration_input",
]


if __name__ == "__main__":  # pragma: no cover - the owner's command
    sys.exit(main())
