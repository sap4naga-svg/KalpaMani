"""Generate one production image's compiled configuration file (ADR-0044 §2, §6).

**Run by the owner at the image gate, never by a task and never by CI.** It reads one
owner-supplied inputs file -- outside the repository, git-ignored -- and writes the
closed, deterministic ``compiled-configuration.json`` the image build copies to
``/etc/kalpamani/compiled-configuration.json``, beside a generation record carrying the
file's SHA-256 (the ``configuration_digest`` the launch tool registers) and the code
identity it was generated from.

```text
python scripts/production_compiled_configuration.py \\
    --entry kalpamani-production-acquire \\
    --inputs <owner path>/acquire-inputs.json \\
    --generated-at 2026-09-20T00:00:00+00:00 \\
    --output docker/production/build/acquire
```

**What it refuses.** A dirty or unknown working tree (the commit it records must be the
one the build context is checked out at); an inputs file carrying any field outside the
entry's closed set -- in particular anything that looks like a secret **value**; a
secret name that is an ARN; an origin address set that is empty or not IPv4; a build
configuration the accepted parser refuses. It prints the digest and the byte count and
never a value from the inputs file.

**Determinism.** The same inputs, commit and ``--generated-at`` produce the same bytes
and the same digest; the wall clock is never read, which is why the instant is an
argument. **Nothing here contacts AWS, a provider, a registry or a container engine.**
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Final

#: The closed field sets of the owner inputs file, per entry. Nothing else is read.
ACQUISITION_INPUT_FIELDS: Final[frozenset[str]] = frozenset({"secret_name", "origin_addresses"})
BUILD_INPUT_FIELDS: Final[frozenset[str]] = frozenset({"build_configuration"})
#: A verification entry (proposed ADR-0045) compiles the origin address set and nothing
#: else: no secret name, no build configuration.
VERIFICATION_INPUT_FIELDS: Final[frozenset[str]] = frozenset({"origin_addresses"})
#: A permission-probe entry (proposed ADR-0048) compiles nothing beyond the code identity:
#: an empty inputs object, and no secret name, origin or build configuration.
PROBE_INPUT_FIELDS: Final[frozenset[str]] = frozenset()
INPUT_FIELDS_BY_ENTRY: Final[dict[str, frozenset[str]]] = {
    "kalpamani-production-acquire": ACQUISITION_INPUT_FIELDS,
    "kalpamani-research-build": BUILD_INPUT_FIELDS,
    "kalpamani-production-acquire-verify": VERIFICATION_INPUT_FIELDS,
    "kalpamani-research-build-verify": VERIFICATION_INPUT_FIELDS,
    "kalpamani-production-acquire-probe": PROBE_INPUT_FIELDS,
    "kalpamani-research-build-probe": PROBE_INPUT_FIELDS,
}

#: Field names whose presence in an inputs file means a secret value is being offered.
#: Refused before anything is parsed, so a value never reaches a document.
FORBIDDEN_INPUT_FIELDS: Final[frozenset[str]] = frozenset(
    {"secret", "secret_value", "api_key", "token", "password", "credential", "secret_arn"}
)

EXIT_OK: Final = 0
EXIT_REFUSED: Final = 1


def _refuse(reason: str) -> int:
    print(f"compiled configuration refused: {reason}")
    return EXIT_REFUSED


def _code_identity(repository: Path) -> tuple[str, str] | None:
    """The commit and tree of a clean checkout, or ``None``. Nothing is printed."""
    import shutil

    git = shutil.which("git")
    if git is None:
        return None
    try:
        status = subprocess.run(  # noqa: S603 - a fixed argument vector
            [git, "status", "--porcelain", "--untracked-files=no"],
            cwd=repository,
            capture_output=True,
            text=True,
            check=True,
        )
        if status.stdout.strip():
            return None
        commit = subprocess.run(  # noqa: S603
            [git, "rev-parse", "HEAD"], cwd=repository, capture_output=True, text=True, check=True
        ).stdout.strip()
        tree = subprocess.run(  # noqa: S603
            [git, "rev-parse", "HEAD^{tree}"],
            cwd=repository,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return commit, tree


def build_parser() -> argparse.ArgumentParser:
    """Exactly four options; every one required."""
    parser = argparse.ArgumentParser(
        prog="production_compiled_configuration", add_help=True, allow_abbrev=False
    )
    parser.add_argument("--entry", required=True)
    parser.add_argument("--inputs", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--output", required=True)
    return parser


def generate(
    *,
    entry_token: str,
    inputs_path: Path,
    generated_at: str,
    output: Path,
    repository: Path,
) -> int:
    """Generate one file, or refuse. Returns the exit status."""
    from kalpamani.data.production.sharadar.compiled import (
        CompiledConfigurationError,
        build_compiled_configuration,
        configuration_digest_of,
        parse_build_configuration,
    )
    from kalpamani.data.production.sharadar.entry import select_entry

    entry = select_entry([entry_token])
    if entry is None:
        return _refuse("the entry is not one of the closed entries")
    identity = _code_identity(repository)
    if identity is None:
        return _refuse("the repository is not a clean checkout at a known commit")
    commit, tree = identity
    try:
        instant = datetime.fromisoformat(generated_at)
    except ValueError:
        return _refuse("--generated-at is not an ISO-8601 instant")
    if instant.tzinfo is None:
        return _refuse("--generated-at must carry a timezone")
    try:
        raw_inputs = inputs_path.read_bytes()
        inputs = json.loads(raw_inputs.decode("utf-8"))
    except (OSError, ValueError):
        return _refuse("the inputs file could not be read as JSON")
    if type(inputs) is not dict:
        return _refuse("the inputs file is not an object")
    if set(inputs) & FORBIDDEN_INPUT_FIELDS or any("secret_value" in k for k in inputs):
        return _refuse("the inputs file offers a secret value; only a secret name is accepted")
    expected = INPUT_FIELDS_BY_ENTRY[entry.value]
    if set(inputs) != expected:
        return _refuse("the inputs file does not carry exactly the entry's fields")
    try:
        if entry.value == "kalpamani-research-build":
            raw = build_compiled_configuration(
                entry=entry,
                code_commit=commit,
                code_tree=tree,
                generated_at=instant,
                build_configuration=parse_build_configuration(inputs["build_configuration"]),
            )
        elif entry.value.endswith("-probe"):
            raw = build_compiled_configuration(
                entry=entry, code_commit=commit, code_tree=tree, generated_at=instant
            )
        else:
            raw = build_compiled_configuration(
                entry=entry,
                code_commit=commit,
                code_tree=tree,
                generated_at=instant,
                secret_name=inputs.get("secret_name"),
                origin_addresses=inputs["origin_addresses"],
            )
    except (CompiledConfigurationError, TypeError, ValueError):
        return _refuse("the inputs do not form a valid compiled configuration")
    digest = configuration_digest_of(raw)
    output.mkdir(parents=True, exist_ok=True)
    (output / "compiled-configuration.json").write_bytes(raw)
    (output / "compiled-configuration.sha256").write_text(digest + "\n", encoding="utf-8")
    record: dict[str, Any] = {
        "entry": entry.value,
        "code_commit": commit,
        "code_tree": tree,
        "generated_at": instant.isoformat(),
        "configuration_digest": digest,
        "configuration_bytes": len(raw),
    }
    (output / "generation-record.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"compiled configuration generated: entry={entry.value} bytes={len(raw)}")
    print(f"configuration_digest={digest}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """Parse and generate. Never prints an input value."""
    arguments = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    return generate(
        entry_token=arguments.entry,
        inputs_path=Path(arguments.inputs),
        generated_at=arguments.generated_at,
        output=Path(arguments.output),
        repository=Path(__file__).resolve().parents[1],
    )


__all__ = [
    "ACQUISITION_INPUT_FIELDS",
    "BUILD_INPUT_FIELDS",
    "FORBIDDEN_INPUT_FIELDS",
    "INPUT_FIELDS_BY_ENTRY",
    "VERIFICATION_INPUT_FIELDS",
    "generate",
    "main",
]


if __name__ == "__main__":  # pragma: no cover - the owner's command
    sys.exit(main())
