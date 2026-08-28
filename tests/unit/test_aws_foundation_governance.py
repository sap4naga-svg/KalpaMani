"""The provisioned AWS foundation, guarded by test rather than by memory.

On 2026-08-27 the ADR-0007 foundation stopped being a description and became real
infrastructure. Two failure modes appear the moment that happens, and neither is
caught by any existing test:

1. **The documents drift back.** A later edit restores "no AWS resource exists"
   because that sentence appears in a dozen places and reads reassuringly. The
   repository would then under-report real infrastructure, which is the same class
   of error as over-reporting it.
2. **An identifier arrives.** The provision record is the one document that
   describes deployed resources, so it is the likeliest place for an account id,
   an ARN or a bucket name to be pasted "just for context". The repository is
   PUBLIC (CLAUDE.md s.3); a mistake there is world-readable immediately.

These are text and AST scans over committed files. **Nothing here contacts AWS**,
reads credentials, or requires a session -- the live account is verified separately
by `scripts/aws_foundation_verify.py`, which needs a profile and is therefore not a
test. What these guard is the repository's account of itself.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INFRA = PROJECT_ROOT / "infra" / "aws" / "research-data-plane"
STATUS_DOC = PROJECT_ROOT / "docs" / "operations" / "aws-foundation-status.md"
VERIFY_SCRIPT = PROJECT_ROOT / "scripts" / "aws_foundation_verify.py"

#: Identifier-shaped material that must never reach a committed file. The 12-digit
#: pattern is the one most likely to arrive by accident, pasted from a console URL.
IDENTIFIER_PATTERNS = {
    "AWS access key id": re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|ANPA|ANVA)[A-Z0-9]{16}\b"),
    "12-digit AWS account id": re.compile(r"(?<![\d.])\d{12}(?![\d.])"),
    "email address": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "account-bearing ARN": re.compile(r"arn:aws:[a-z0-9-]*:[a-z0-9-]*:\d{12}:"),
}

#: Facts the provision record must carry. Without them it is a status document that
#: does not state the status.
REQUIRED_STATUS_FACTS = (
    "2026-08-27",
    "us-east-1",
    "v1.16.0",
    "v6.62.0",
    "HARD-DISABLED",
    "PROPOSED",
)

#: AWS CLI verbs that mutate. `scripts/aws_foundation_verify.py` is described as
#: read-only, and a verification tool that can change what it verifies is worse
#: than no verification tool.
MUTATING_CLI_VERBS = (
    "create-",
    "delete-",
    "put-",
    "update-",
    "modify-",
    "attach-",
    "detach-",
    "terminate-",
    "run-task",
    "register-",
    "deregister-",
)

STATUS_DOCUMENTS = ("CLAUDE.md", "README.md")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tracked_infra_files() -> list[Path]:
    """Files under infra/ that git tracks.

    Deliberately not a directory walk. Operating the provisioned foundation
    requires a real, git-ignored `terraform.tfvars` holding the account id; a walk
    would find it and report the ignore rule working as a failure.
    """
    result = subprocess.run(  # noqa: S603
        ["git", "-C", str(PROJECT_ROOT), "ls-files", "--", str(INFRA)],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("git is unavailable; the committed-file scan cannot run")
    return [PROJECT_ROOT / line for line in result.stdout.split() if line]


# ---------------------------------------------------------------------------
# The provision record
# ---------------------------------------------------------------------------


def test_the_provision_record_exists() -> None:
    assert STATUS_DOC.is_file(), f"missing provision record: {STATUS_DOC}"


@pytest.mark.parametrize("fact", REQUIRED_STATUS_FACTS)
def test_the_provision_record_states_the_governed_facts(fact: str) -> None:
    assert fact in _read(STATUS_DOC), f"the provision record does not record {fact!r}"


def test_the_provision_record_reports_the_foundation_as_provisioned() -> None:
    text = _read(STATUS_DOC)
    assert "PROVISIONED" in text, "the provision record does not say the foundation is provisioned"


@pytest.mark.parametrize(("label", "pattern"), sorted(IDENTIFIER_PATTERNS.items()))
def test_the_provision_record_carries_no_identifier(label: str, pattern: re.Pattern[str]) -> None:
    hits = [n for n, line in enumerate(_read(STATUS_DOC).splitlines(), 1) if pattern.search(line)]
    assert not hits, f"{label} found in the provision record at line(s) {hits}"


def test_the_provision_record_does_not_present_the_smoke_test_as_the_rehearsal() -> None:
    """The five-step synthetic smoke test is not the 15-step vendor-termination rehearsal.

    They differ in identity, scope and evidence: the smoke test ran as the operator
    rather than the deletion role, touched one object, started no multipart upload
    and produced no receipt. Recording one as the other would retire an obligation
    that has not been discharged.
    """
    flat = _read(STATUS_DOC).replace("*", "").lower()
    assert "not the 15-step" in flat, "the smoke test is not distinguished from the rehearsal"


# ---------------------------------------------------------------------------
# The status documents must not drift back to "nothing exists"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", STATUS_DOCUMENTS)
def test_the_status_documents_record_the_account_as_created(name: str) -> None:
    text = _read(PROJECT_ROOT / name)
    assert re.search(r"AWS account.*NOT CREATED", text) is None, (
        f"{name} still reports the AWS account as NOT CREATED"
    )
    assert re.search(r"AWS account.*CREATED", text) is not None, (
        f"{name} does not record the AWS account as created"
    )


@pytest.mark.parametrize("name", STATUS_DOCUMENTS)
def test_the_status_documents_still_bound_further_spend(name: str) -> None:
    """Provisioning a platform is not permission to spend on it (CLAUDE.md s.4.21)."""
    text = _read(PROJECT_ROOT / name)
    assert re.search(r"(?i)spend.{0,60}NOT AUTHORIZED", text) is not None, (
        f"{name} does not bound cloud spend beyond the idle foundation"
    )


@pytest.mark.parametrize("name", STATUS_DOCUMENTS)
def test_the_status_documents_keep_provider_and_vendor_data_at_none(name: str) -> None:
    text = _read(PROJECT_ROOT / name)
    assert "vendor data NONE" in text or "vendor data" in text, (
        f"{name} does not state the vendor-data position"
    )
    assert "G1" in text and "OPEN" in text, f"{name} does not record the gates as open"


# ---------------------------------------------------------------------------
# Nothing identity-bearing became committable when the foundation became real
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("label", "pattern"), sorted(IDENTIFIER_PATTERNS.items()))
def test_no_committed_infra_file_carries_an_identifier(
    label: str, pattern: re.Pattern[str]
) -> None:
    hits: list[str] = []
    for path in _tracked_infra_files():
        if not path.is_file():
            continue
        for lineno, line in enumerate(_read(path).splitlines(), 1):
            if pattern.search(line):
                hits.append(f"{path.name}:{lineno}")
    assert not hits, f"{label} committed under infra/: {hits[:5]}"


def test_no_real_tfvars_state_or_plan_file_is_committed() -> None:
    tracked = {p.name for p in _tracked_infra_files()}
    stray = sorted(
        name
        for name in tracked
        if name.endswith((".tfstate", ".tfplan"))
        or (name.endswith(".tfvars") and name != "terraform.tfvars.example")
    )
    assert not stray, f"identity-bearing Terraform files are committed: {stray}"


@pytest.mark.parametrize("rule", ("*.tfstate", "*.tfvars", "*.tfplan", "**/.terraform/"))
def test_gitignore_still_excludes_terraform_state_and_variables(rule: str) -> None:
    gitignore = _read(PROJECT_ROOT / ".gitignore")
    assert rule in gitignore, f".gitignore no longer excludes {rule}"


def test_the_committed_backend_declaration_carries_no_values() -> None:
    """The tracked backend block must stay empty.

    A state bucket name in a public repository names the exact object an attacker
    should try to read. The real values live in an uncommitted backend file and are
    supplied with `-backend-config` at init.
    """
    versions = _read(INFRA / "versions.tf")
    assert 'backend "s3" {}' in versions, "the empty S3 backend declaration is missing"
    for leaked in ("bucket ", "key ", "use_lockfile"):
        pattern = re.compile(rf"^\s*{re.escape(leaked.strip())}\s*=", re.MULTILINE)
        offending = [
            line
            for line in versions.splitlines()
            if pattern.match(line) and not line.strip().startswith("#")
        ]
        assert not offending, f"backend value {leaked.strip()!r} is committed: {offending}"


def test_no_dynamodb_lock_table_is_declared() -> None:
    """S3 native locking replaced the DynamoDB table: one fewer always-on billable resource."""
    hcl = "\n".join(_read(p) for p in sorted(INFRA.glob("*.tf")))
    stripped = "\n".join(line for line in hcl.splitlines() if not line.strip().startswith("#"))
    assert "aws_dynamodb_table" not in stripped, "a DynamoDB lock table would bill continuously"


def test_the_terraform_still_requires_a_version_that_supports_native_locking() -> None:
    """`use_lockfile` does not exist before Terraform 1.10.

    An older Terraform would init this backend and silently ignore the locking --
    a lock believed to be held and not held.
    """
    versions = _read(INFRA / "versions.tf")
    match = re.search(r'required_version\s*=\s*">=\s*(\d+)\.(\d+)', versions)
    assert match is not None, "no required_version constraint found"
    major, minor = int(match.group(1)), int(match.group(2))
    assert (major, minor) >= (1, 10), f"required_version {major}.{minor} predates use_lockfile"


# ---------------------------------------------------------------------------
# The verification tool must not be able to change what it verifies
# ---------------------------------------------------------------------------


def test_the_verification_script_issues_no_mutating_aws_call() -> None:
    tree = ast.parse(_read(VERIFY_SCRIPT))
    literals = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)]
    strings = [s for s in literals if isinstance(s, str)]
    offending = sorted({s for s in strings for verb in MUTATING_CLI_VERBS if s.startswith(verb)})
    assert not offending, f"the verification script names mutating AWS verbs: {offending}"


def test_the_verification_script_refuses_an_unpinned_profile() -> None:
    """A stale AWS_PROFILE is the AWS form of the wrong-account problem in CLAUDE.md s.3."""
    source = _read(VERIFY_SCRIPT)
    assert "EXPECTED_PROFILE" in source, "the verification script does not pin a profile"
    assert "REFUSED" in source, "the verification script does not refuse a wrong profile"
