"""The repository boundary around private Sharadar qualification material.

The harness tests next door prove the *program* keeps its output private. These prove
the *repository* does -- that no licensed row, no empirical conclusion, no private
credential and no AWS identifier has arrived in a committed file, and that no committed
code has grown a path that would send one somewhere.

Why this is a separate module. The repository is **PUBLIC** (CLAUDE.md s.3), and
[ADR-0008] s.3 records two clauses that make a mistake here unrecoverable rather than
merely embarrassing: Terms s.4 bars redistributing Services Data, and s.8 bars disclosing
evaluation conclusions to any outside individual or entity. INC-0002 already established
that a force-push does not undo a public commit. So the interesting failure is not "the
harness printed something" -- it is "a file appeared", and only a scan over what git
actually tracks can see that.

**Nothing here contacts AWS, Sharadar or any network.** These are text and AST scans over
committed files.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HARNESS = PROJECT_ROOT / "scripts" / "sharadar_private_qualification.py"
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "sharadar_qualification.py"
SRC = PROJECT_ROOT / "src"
SCRIPTS = PROJECT_ROOT / "scripts"
TESTS = PROJECT_ROOT / "tests"

#: The one file allowed to contain CSV that looks like a provider response. It is
#: hand-authored and fictitious, and a separate test below holds it to that.
SYNTHETIC_CSV_ALLOWLIST = frozenset({FIXTURES})

#: Column names distinctive enough to identify a Sharadar-shaped payload.
SHARADAR_COLUMNS = frozenset(
    {
        "closeadj",
        "closeunadj",
        "permaticker",
        "eventcodes",
        "contraticker",
        "contraname",
        "isdelisted",
        "reportperiod",
        "calendardate",
        "lastupdated",
        "siccode",
        "scalemarketcap",
    }
)

#: Identifier-shaped material that must not reach a committed file on this surface.
IDENTIFIER_PATTERNS = {
    "AWS access key id": re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|ANPA|ANVA)[A-Z0-9]{16}\b"),
    "12-digit AWS account id": re.compile(r"(?<![\d.])\d{12}(?![\d.])"),
    "account-bearing ARN": re.compile(r"arn:aws:[a-z0-9-]*:[a-z0-9-]*:\d{12}:"),
    "email address": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "AWS SSO start URL": re.compile(r"https://[a-z0-9-]+\.awsapps\.com/start"),
}

#: External model providers. Sending licensed rows or an evaluation conclusion to any of
#: them would breach Terms s.4 and s.8 and CLAUDE.md s.4.22 at the same time.
EXTERNAL_AI_MARKERS = (
    "api.openai.com",
    "api.anthropic.com",
    "generativelanguage.googleapis.com",
    "api.cohere.ai",
    "openai",
    "anthropic",
    "langchain",
    "bedrock-runtime",
)

#: SDKs the harness must not reach for. It is stdlib-only by design; AWS goes through the
#: CLI in a subprocess so that no cloud SDK becomes a project dependency.
FORBIDDEN_IMPORTS = frozenset(
    {
        "boto3",
        "botocore",
        "requests",
        "httpx",
        "urllib3",
        "pandas",
        "polars",
        "pyarrow",
        "duckdb",
        "openai",
        "anthropic",
    }
)

#: Scripts that run unattended or in a review loop. None of them may reach the harness:
#: a provider conclusion produced by an audit is a conclusion in a log.
UNATTENDED_SCRIPTS = (
    "phase1_preflight.py",
    "phase2_preflight.py",
    "phase3_docs_audit.py",
    "test_integrity_audit.py",
    "aws_foundation_verify.py",
    "verify_purge.py",
)


def tracked_files() -> list[Path]:
    """Every file git actually tracks.

    Deliberately not a directory walk. A real run writes licensed payloads under
    `.runtime/`, which is git-ignored; walking the tree would find them and report the
    ignore rule *working* as a failure -- the same mistake the AWS audit had to fix.
    """
    result = subprocess.run(  # noqa: S603
        ["git", "-C", str(PROJECT_ROOT), "ls-files"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        # NOT a skip. "We could not check" must read as a failure in a governance test.
        pytest.fail("git ls-files failed; committed-file governance cannot be verified")
    return [PROJECT_ROOT / line for line in result.stdout.splitlines() if line]


def _text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _tracked_text_files() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for path in tracked_files():
        content = _text(path)
        if content is not None:
            out.append((path, content))
    return out


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


# ---------------------------------------------------------------------------
# No qualification artifact is committed
# ---------------------------------------------------------------------------

FORBIDDEN_PATH_FRAGMENTS = (
    "qualification/sharadar",
    "private-qualification-report",
    "private-report",
    ".runtime/",
)


def test_no_qualification_artifact_path_is_tracked() -> None:
    offenders = [
        str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
        for path in tracked_files()
        if any(
            fragment in str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
            for fragment in FORBIDDEN_PATH_FRAGMENTS
        )
    ]
    assert offenders == [], f"qualification material must never be committed. Found: {offenders}"


def test_the_private_report_filename_is_not_a_tracked_file() -> None:
    offenders = [
        str(path) for path in tracked_files() if path.name == "private-qualification-report.html"
    ]
    assert offenders == []


def test_the_runtime_report_location_is_git_ignored() -> None:
    """The ignore rule is the control. Assert it, rather than trusting the pattern list."""
    probe = ".runtime/phase3/sharadar/private-qualification-report.html"
    result = subprocess.run(  # noqa: S603
        ["git", "-C", str(PROJECT_ROOT), "check-ignore", "-q", probe],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"{probe} is NOT git-ignored"


def test_the_harness_writes_its_report_only_under_the_runtime_area() -> None:
    source = HARNESS.read_text(encoding="utf-8")
    assert 'RUNTIME_ROOT = REPO_ROOT / ".runtime" / "phase3" / "sharadar"' in source


# ---------------------------------------------------------------------------
# No vendor row and no evaluation conclusion is committed
# ---------------------------------------------------------------------------


def _csv_header_columns(line: str) -> set[str]:
    """The column set if ``line`` reads as a bare CSV header, else empty."""
    stripped = line.strip()
    if stripped.count(",") < 4 or " " in stripped or "`" in stripped or "|" in stripped:
        return set()
    tokens = stripped.split(",")
    if not all(re.fullmatch(r"[a-z][a-z0-9_]*", token) for token in tokens):
        return set()
    return set(tokens)


def test_no_committed_file_carries_a_provider_shaped_csv_header() -> None:
    offenders: list[str] = []
    for path, content in _tracked_text_files():
        if path in SYNTHETIC_CSV_ALLOWLIST:
            continue
        for lineno, line in enumerate(content.splitlines(), 1):
            if len(_csv_header_columns(line) & SHARADAR_COLUMNS) >= 2:
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{lineno}")
    assert offenders == [], f"a provider-shaped payload appears in a committed file: {offenders}"


def _looks_like_a_data_row(line: str) -> bool:
    stripped = line.strip().strip('"')
    if stripped.count(",") < 4:
        return False
    first = stripped.split(",", 1)[0]
    return bool(re.fullmatch(r"[A-Z]{1,5}", first))


def test_no_committed_file_carries_a_provider_shaped_data_row() -> None:
    offenders: list[str] = []
    for path, content in _tracked_text_files():
        if path in SYNTHETIC_CSV_ALLOWLIST:
            continue
        for lineno, line in enumerate(content.splitlines(), 1):
            if _looks_like_a_data_row(line):
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{lineno}")
    assert offenders == [], f"a ticker-keyed data row appears in a committed file: {offenders}"


def test_the_synthetic_fixtures_are_recognisably_fictitious() -> None:
    """The one allowlisted file must earn the allowlist on every run, not once."""
    content = FIXTURES.read_text(encoding="utf-8")
    assert "Fictitious" in content
    assert "FAKE" in content
    assert "999001" in content
    assert "AAPL" not in content, "no real security may appear in a committed fixture"
    assert "synthetic" in content.lower()


def test_no_empirical_qualification_status_is_committed_as_a_result() -> None:
    """Methodology may be public. A *result* may not.

    The distinction is enforceable because a result reads as a test id bound to a status
    -- a ``P<n>`` followed by one of the status words -- whereas methodology names the
    vocabulary without binding it to any test. This docstring deliberately does not spell
    an example out: doing so would make the guard's own source the first thing it flags.
    """
    verdict = re.compile(
        r"\bP[1-9]\b\s*[:=—-]\s*"
        r"(TESTED|PARTIALLY_TESTED|DOCUMENTATION_RESOLVED|"
        r"NOT_TESTABLE_WITH_PUBLIC_SAMPLE|DEFERRED|INCONCLUSIVE)\b"
    )
    offenders: list[str] = []
    for path, content in _tracked_text_files():
        if path in {HARNESS, FIXTURES} or path.name.startswith("test_sharadar"):
            continue
        for lineno, line in enumerate(content.splitlines(), 1):
            if verdict.search(line):
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{lineno}")
    assert offenders == [], (
        f"an empirical provider verdict appears in a committed file: {offenders}"
    )


def test_no_private_recommendation_value_is_committed_as_a_conclusion() -> None:
    """The three recommendation values may be *named* in the harness and its ADR.

    They may not appear anywhere that reads as this project's actual conclusion, because
    that conclusion is exactly what Terms s.8 keeps private.
    """
    allowed = {
        HARNESS,
        PROJECT_ROOT / "tests" / "unit" / "test_sharadar_qualification_harness.py",
        PROJECT_ROOT / "tests" / "unit" / "test_sharadar_qualification_boundary.py",
        PROJECT_ROOT
        / "docs"
        / "decisions"
        / "ADR-0008-sharadar-personal-use-license-and-private-qualification.md",
    }
    stated = re.compile(
        r"(recommendation|conclusion|verdict|result)\s*(is|was|:)\s*\**"
        r"(PROCEED_TO_PROVIDER_REALISTIC_IMPLEMENTATION|HOLD_FOR_ADDITIONAL_PRIVATE_SAMPLE|"
        r"REJECT_FOR_PHASE3A)",
        re.IGNORECASE,
    )
    offenders: list[str] = []
    for path, content in _tracked_text_files():
        if path in allowed:
            continue
        if stated.search(content):
            offenders.append(str(path.relative_to(PROJECT_ROOT)))
    assert offenders == [], f"a private provider conclusion appears committed: {offenders}"


# ---------------------------------------------------------------------------
# Credentials and identifiers
# ---------------------------------------------------------------------------


def test_the_only_committed_api_key_literal_is_the_vendor_public_test_key() -> None:
    """A rule, not an enumeration: real-looking key values cannot be added quietly.

    ``test-api-key`` is the vendor's own published test token (`PSR-SHD-109`) and is
    allowlisted by name. Anything else must be openly marked synthetic or redacted.
    """
    pattern = re.compile(r"api[_-]?key\s*[=:]\s*[\"']?([A-Za-z0-9_.\-]{3,})")
    offenders: list[str] = []
    for path, content in _tracked_text_files():
        for match in pattern.finditer(content):
            value = match.group(1)
            if not re.search(r"[A-Za-z0-9]", value):
                continue  # a documentation placeholder such as `api_key=...`
            if value == "test-api-key" or value.startswith(("synthetic", "redacted", "your")):
                continue
            offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {value[:12]}")
    assert offenders == [], f"a non-public key-shaped literal is committed: {offenders}"


@pytest.mark.parametrize("label", sorted(IDENTIFIER_PATTERNS))
def test_no_aws_identifier_reaches_the_qualification_surface(label: str) -> None:
    """Scoped to the files this work adds, and named so the scope is honest.

    A repository-wide identifier scan already exists for `infra/`; widening this one to
    every document would make it fail on pre-existing prose rather than on a real leak.
    """
    surface = [
        HARNESS,
        FIXTURES,
        PROJECT_ROOT / "tests" / "unit" / "test_sharadar_qualification_harness.py",
        PROJECT_ROOT / "tests" / "unit" / "test_sharadar_qualification_boundary.py",
        PROJECT_ROOT
        / "docs"
        / "decisions"
        / "ADR-0008-sharadar-personal-use-license-and-private-qualification.md",
    ]
    pattern = IDENTIFIER_PATTERNS[label]
    offenders: list[str] = []
    for path in surface:
        content = _text(path)
        assert content is not None, f"expected file is missing or unreadable: {path}"
        if pattern.search(content):
            offenders.append(str(path.relative_to(PROJECT_ROOT)))
    assert offenders == [], f"{label} found in: {offenders}"


def test_the_harness_never_prints_a_bucket_name_or_an_account() -> None:
    """Bucket names come from Terraform state. They are read into memory and stay there."""
    source = HARNESS.read_text(encoding="utf-8")
    tree = ast.parse(source)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id != "print":
            continue
        for argument in node.args:
            names = {n.id for n in ast.walk(argument) if isinstance(n, ast.Name)}
            attributes = {n.attr for n in ast.walk(argument) if isinstance(n, ast.Attribute)}
            if names & {"buckets", "outputs"} or attributes & {"licensed", "control"}:
                offenders.append(ast.unparse(node)[:80])
    assert offenders == [], f"a print() may carry an identifier: {offenders}"


# ---------------------------------------------------------------------------
# No network from tests, no AI path, no production adapter
# ---------------------------------------------------------------------------

NETWORK_CALLS = frozenset(
    {
        "urlopen",
        "create_connection",
        "socket",
        "HTTPConnection",
        "HTTPSConnection",
        "getaddrinfo",
        "connect",
    }
)


def test_no_test_module_opens_a_network_connection() -> None:
    offenders: list[str] = []
    for path in _python_files(TESTS):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else node.func.id
                if isinstance(node.func, ast.Name)
                else ""
            )
            if name in NETWORK_CALLS:
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {name}")
    assert offenders == [], f"a test reaches the network: {offenders}"


def test_the_harness_reaches_exactly_one_vendor_host() -> None:
    hosts = {
        match.group(1)
        for match in re.finditer(r"https?://([A-Za-z0-9.\-]+)", HARNESS.read_text(encoding="utf-8"))
    }
    assert hosts == {"api.sharadar.com", "sharadar.com"}, f"unexpected hosts: {sorted(hosts)}"


@pytest.mark.parametrize("marker", EXTERNAL_AI_MARKERS)
def test_no_external_ai_path_exists_for_qualification_material(marker: str) -> None:
    """s.8 evaluation output and s.4 vendor rows must have no route to a model provider."""
    surface = [HARNESS, FIXTURES]
    offenders = [
        str(path.relative_to(PROJECT_ROOT))
        for path in surface
        if marker in (_text(path) or "").lower()
    ]
    assert offenders == [], f"{marker!r} appears on the qualification surface: {offenders}"


def test_the_harness_imports_no_sdk_and_stays_standard_library() -> None:
    roots = {module.split(".")[0] for module in _imports(HARNESS)}
    assert not roots & FORBIDDEN_IMPORTS, f"forbidden imports: {sorted(roots & FORBIDDEN_IMPORTS)}"


def test_the_project_still_declares_no_runtime_dependency() -> None:
    content = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "dependencies = []" in content


# ---------------------------------------------------------------------------
# No production adapter, and no automated invocation
# ---------------------------------------------------------------------------


def test_no_production_module_mentions_the_provider() -> None:
    """G1 is open. Until a provider is selected, no production module names one."""
    offenders = [
        str(path.relative_to(PROJECT_ROOT))
        for path in _python_files(SRC)
        if "sharadar" in path.read_text(encoding="utf-8").lower()
    ]
    assert offenders == [], f"production code names the provider: {offenders}"


def test_no_production_provider_adapter_exists() -> None:
    assert not (SRC / "kalpamani" / "data" / "ingest" / "sharadar").exists()


def test_no_production_module_imports_the_qualification_harness() -> None:
    offenders = [
        str(path.relative_to(PROJECT_ROOT))
        for path in _python_files(SRC)
        if "sharadar_private_qualification" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"production code imports the harness: {offenders}"


def test_the_harness_lives_outside_the_installed_package() -> None:
    assert HARNESS.is_file()
    assert not HARNESS.is_relative_to(SRC)


#: Execution primitives. Deliberately narrower than "mentions the harness": the docs audit
#: legitimately READS the harness as text to assert its safety properties, and banning the
#: mention would force that audit to stop checking the very thing it should check. What must
#: never appear is a way to RUN it.
EXECUTION_MARKERS = (
    "import sharadar_private_qualification",
    "from sharadar_private_qualification",
    "run_private_qualification(",
    "exec_module",
    "runpy",
)


@pytest.mark.parametrize("script", UNATTENDED_SCRIPTS)
def test_no_unattended_script_executes_the_qualification_harness(script: str) -> None:
    """Reading the harness is fine. Running it from automation is not.

    A provider conclusion produced by a preflight or an audit is a conclusion in a log, and
    Terms s.8 makes a log a disclosure channel.
    """
    path = SCRIPTS / script
    assert path.is_file(), f"expected script is missing: {script}"
    content = path.read_text(encoding="utf-8")

    found = [marker for marker in EXECUTION_MARKERS if marker in content]
    assert found == [], f"{script} could execute the harness: {found}"

    # A subprocess handed the harness path would run it without importing it.
    tree = ast.parse(content)
    launches: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        rendered = ast.unparse(node)
        if "subprocess" in rendered and "sharadar" in rendered:
            launches.append(rendered[:80])
    assert launches == [], f"{script} may launch the harness in a subprocess: {launches}"


def test_the_deletion_runbook_still_covers_the_qualification_prefix() -> None:
    """Qualification evidence is licensed, so it must sit inside the deletion surface."""
    runbook = PROJECT_ROOT / "docs" / "runbooks" / "vendor-data-cloud-deletion.md"
    content = runbook.read_text(encoding="utf-8")
    assert "qualification/" in content


def test_the_harness_stores_qualification_material_only_under_the_licensed_prefix() -> None:
    source = HARNESS.read_text(encoding="utf-8")
    assert 'return f"qualification/sharadar/{run_id}"' in source
    assert "assert_licensed_destination" in source
