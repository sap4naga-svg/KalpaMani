"""Terraform is unreachable from the Run A acquisition path (ADR-0023).

The guard this replaces was ``assert "terraform" not in source.lower()`` over the
entry point's own text. It was true and it was worthless: the entry point never
spelled the word, it said ``from aws_foundation_verify import tf_outputs``, and the
subprocess lived one module away. A dependency you cannot see by reading one file is
exactly the dependency a source-string check cannot find.

Two independent defenses replace it, because either one alone can be argued around:

1. **A name-level call graph.** Every top-level definition of the acquisition entry
   point is walked, every name it references is resolved through that module's own
   import bindings into the defining module, and the walk repeats. Reaching
   ``aws_foundation_verify`` is not enough to condemn the path -- the identity gate
   legitimately lives there -- so the graph is followed *per name* rather than per
   module, and the question is whether ``tf_outputs`` and the pinned Terraform
   executable are in the closure.

2. **A runtime sentinel.** The real verifier module is loaded, ``tf_outputs`` and its
   ``subprocess`` are replaced with traps, and stage 6 is then run for real against a
   synthetic private binding. A trap that never fires while the stage succeeds is
   evidence the static answer describes what actually happens.

Both are driven through functions that take the entry point's *source*, so the
mutation tests at the bottom can reintroduce the defect in memory -- directly, behind
an alias, through the foundation profile, and through a raw environment variable --
and prove each guard fails. A guard nobody has watched fail is a guard nobody has
tested.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pytest

from kalpamani.data.qualify.sharadar import runtime_binding as rb

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
SRC = REPO_ROOT / "src"
ACQUIRE_PATH = SCRIPTS / "sharadar_empirical_qualification.py"
VERIFIER_PATH = SCRIPTS / "aws_foundation_verify.py"

ACQUIRE_KEY: Final = "scripts:sharadar_empirical_qualification"
VERIFIER_KEY: Final = "scripts:aws_foundation_verify"
BINDING_KEY: Final = "src:kalpamani.data.qualify.sharadar.runtime_binding"

#: The module-level statements, gathered under one pseudo-name so they are walked
#: alongside the real definitions.
MODULE_BODY: Final = "<module>"

ACQUIRE_SOURCE: Final = ACQUIRE_PATH.read_text(encoding="utf-8")

#: Synthetic, and matching no deployment. Reused by the sentinel and integration
#: tests below.
ACCOUNT: Final = "000000000000"
BUCKET: Final = "synthetic-licensed-bucket-zz"
CURRENT: Final = "S-1-5-21-0-0-0-1001"
COMMIT: Final = "0123456789abcdef0123456789abcdef01234567"
TREE: Final = "89abcdef0123456789abcdef0123456789abcdef"
ENVELOPE: Final = "0123456789abcdef" * 4


# ---------------------------------------------------------------------------
# A name-level call graph over repository-owned modules
# ---------------------------------------------------------------------------

Definition = tuple[str, str]


def _module_file(name: str) -> tuple[str, Path] | None:
    """Where a repository-owned module lives, or ``None`` when it is external."""
    if name.startswith("kalpamani"):
        parts = name.split(".")
        package = SRC.joinpath(*parts, "__init__.py")
        if package.is_file():
            return f"src:{name}", package
        module = SRC.joinpath(*parts[:-1], f"{parts[-1]}.py")
        if module.is_file():
            return f"src:{name}", module
        return None
    script = SCRIPTS / f"{name}.py"
    if script.is_file():
        return f"scripts:{name}", script
    return None


@dataclass(frozen=True)
class _Analysis:
    """One module's top-level definitions and the names its imports bind."""

    key: str
    definitions: dict[str, list[ast.AST]]
    bindings: dict[str, tuple[str, str]]


def _import_bindings(nodes: list[ast.AST]) -> dict[str, tuple[str, str]]:
    """Local name -> ``(module, original name)``. ``"*"`` marks a whole module."""
    bindings: dict[str, tuple[str, str]] = {}
    for node in nodes:
        for inner in ast.walk(node):
            if isinstance(inner, ast.ImportFrom) and inner.module and inner.level == 0:
                for alias in inner.names:
                    bindings[alias.asname or alias.name] = (inner.module, alias.name)
            elif isinstance(inner, ast.Import):
                for alias in inner.names:
                    bindings[alias.asname or alias.name.split(".")[0]] = (alias.name, "*")
    return bindings


def _strip_docstrings(tree: ast.Module) -> ast.Module:
    """Drop every docstring, so prose can neither satisfy nor fail a check.

    The literal scan below reads string constants as evidence of what the code can
    *do*. A docstring explaining that Terraform is no longer reached would otherwise
    be indistinguishable from an argv naming the executable.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                body.pop(0)
    return tree


def _analyse(key: str, source: str) -> _Analysis:
    tree = _strip_docstrings(ast.parse(source))
    definitions: dict[str, list[ast.AST]] = {MODULE_BODY: []}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            definitions.setdefault(node.name, []).append(node)
            continue
        definitions[MODULE_BODY].append(node)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            definitions.setdefault(node.target.id, []).append(node)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    definitions.setdefault(target.id, []).append(node)
    return _Analysis(
        key=key,
        definitions=definitions,
        bindings=_import_bindings(list(tree.body)),
    )


@dataclass(frozen=True)
class Reachability:
    """Everything the acquisition path can reach, and every literal it can see."""

    definitions: frozenset[Definition]
    literals: frozenset[str]


def _reachability(entry_source: str) -> Reachability:
    """The transitive, name-level closure of the acquisition entry point."""
    sources: dict[str, str] = {ACQUIRE_KEY: entry_source}
    analyses: dict[str, _Analysis] = {}

    def analysis_of(key: str, path: Path | None) -> _Analysis:
        if key not in analyses:
            if key not in sources:
                assert path is not None
                sources[key] = path.read_text(encoding="utf-8")
            analyses[key] = _analyse(key, sources[key])
        return analyses[key]

    entry = analysis_of(ACQUIRE_KEY, ACQUIRE_PATH)
    pending: list[Definition] = [(ACQUIRE_KEY, name) for name in entry.definitions]
    reached: set[Definition] = set()
    literals: set[str] = set()

    while pending:
        current = pending.pop()
        if current in reached:
            continue
        reached.add(current)
        key, name = current
        owner = analyses[key]
        nodes = owner.definitions.get(name, [])
        bindings = dict(owner.bindings)
        bindings.update(_import_bindings(nodes))

        referenced: set[str] = set()
        for node in nodes:
            for inner in ast.walk(node):
                if isinstance(inner, ast.Name):
                    referenced.add(inner.id)
                elif isinstance(inner, ast.Attribute) and isinstance(inner.value, ast.Name):
                    alias = bindings.get(inner.value.id)
                    if alias is not None and alias[1] == "*":
                        located = _module_file(alias[0])
                        if located is not None:
                            analysis_of(located[0], located[1])
                            pending.append((located[0], inner.attr))
                elif isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                    literals.add(inner.value)

        for referred in referenced:
            bound = bindings.get(referred)
            if bound is not None:
                module, original = bound
                if original == "*":
                    continue
                located = _module_file(module)
                if located is None:
                    continue
                analysis_of(located[0], located[1])
                pending.append((located[0], original))
            elif referred in owner.definitions:
                pending.append((key, referred))

    return Reachability(definitions=frozenset(reached), literals=frozenset(literals))


#: Definitions the acquisition path must never be able to reach. Each is a real
#: name in the governed verifier, so a miss here is a miss about something that
#: exists rather than about a name nobody wrote.
FORBIDDEN: Final[tuple[tuple[Definition, str], ...]] = (
    ((VERIFIER_KEY, "tf_outputs"), "the Terraform state read"),
    ((VERIFIER_KEY, "TERRAFORM"), "the pinned Terraform executable"),
    ((VERIFIER_KEY, "backend_settings"), "the Terraform backend configuration"),
    ((VERIFIER_KEY, "BACKEND_HCL"), "the backend configuration file"),
    ((VERIFIER_KEY, "check_state_backend"), "the state-bucket S3 read"),
    ((VERIFIER_KEY, "EXPECTED_PROFILE"), "the shared foundation profile"),
)

#: The one Terraform-adjacent thing the closure may mention: ``terraform.tfvars``,
#: the local, git-ignored account-binding variables file the identity gate already
#: reads. It is a plain local file read -- no subprocess, no state, no backend -- and
#: it is permitted anywhere inside a literal so the gate's own refusal *messages*,
#: which name the file in prose, do not read as a Terraform reach.
PERMITTED_MENTION: Final = "terraform.tfvars"


def _mentions_terraform(literal: str) -> bool:
    """Whether a literal names Terraform for any reason other than that one file."""
    return "terraform" in literal.lower().replace(PERMITTED_MENTION, "")


def _terraform_findings(entry_source: str) -> list[str]:
    """Every way this acquisition path could reach Terraform. Empty when it cannot."""
    reach = _reachability(entry_source)
    findings = [
        f"{description} is reachable"
        for definition, description in FORBIDDEN
        if definition in reach.definitions
    ]
    findings += [
        f"a Terraform literal is reachable: {literal!r}"
        for literal in sorted(reach.literals)
        if _mentions_terraform(literal)
    ]
    if "-chdir=" in "".join(sorted(reach.literals)):
        findings.append("a Terraform working-directory argument is reachable")
    if (BINDING_KEY, "load_runtime_binding") not in reach.definitions:
        findings.append("the private runtime binding loader is not reachable")
    return findings


def _environment_names(entry_source: str) -> set[str]:
    """Every environment-variable name the entry point reads, as a literal."""
    tree = ast.parse(entry_source)
    literals: dict[str, str] = {}
    for node in tree.body:
        target: str | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            target, value = node.targets[0].id, node.value
        if target and isinstance(value, ast.Constant) and isinstance(value.value, str):
            literals[target] = value.value

    def _key(expression: ast.expr) -> str:
        if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
            return expression.value
        if isinstance(expression, ast.Name) and expression.id in literals:
            return literals[expression.id]
        raise AssertionError("an environment key is not a module-level literal")

    names: set[str] = set()
    for reference in ast.walk(tree):
        if (
            isinstance(reference, ast.Call)
            and isinstance(reference.func, ast.Attribute)
            and reference.func.attr == "get"
            and isinstance(reference.func.value, ast.Attribute)
            and reference.func.value.attr == "environ"
            and reference.args
        ):
            names.add(_key(reference.args[0]))
        elif (
            isinstance(reference, ast.Subscript)
            and isinstance(reference.value, ast.Attribute)
            and reference.value.attr == "environ"
        ):
            names.add(_key(reference.slice))
    return names


# -- the analyzer is worth trusting -------------------------------------------


def test_the_call_graph_reaches_into_the_governed_verifier() -> None:
    """Positive controls, so a negative result below means something.

    An analyzer that resolved nothing would report every forbidden name absent and
    look like a passing guard. These four prove it crosses the module boundary, then
    a second hop *inside* the verifier, and then into the new loader under ``src/``.
    """
    reach = _reachability(ACQUIRE_SOURCE)
    for control in (
        (VERIFIER_KEY, "qualification_identity_gate"),
        (VERIFIER_KEY, "expected_account"),
        (VERIFIER_KEY, "_run_aws"),
        (BINDING_KEY, "load_runtime_binding"),
        (BINDING_KEY, "windows_file_security"),
    ):
        assert control in reach.definitions, control


def test_the_call_graph_sees_string_literals_from_reached_modules() -> None:
    """A second control, for the literal scan the Terraform check also relies on."""
    reach = _reachability(ACQUIRE_SOURCE)
    assert "sts" in reach.literals
    assert "terraform.tfvars" in reach.literals


# -- defense one: the acquisition path cannot reach Terraform -----------------


def test_the_acquisition_path_cannot_reach_terraform() -> None:
    assert _terraform_findings(ACQUIRE_SOURCE) == []


def test_the_acquisition_path_reads_exactly_two_environment_names() -> None:
    """The governed profile and the secret identifier. The bucket is not among them."""
    assert _environment_names(ACQUIRE_SOURCE) == {
        "AWS_PROFILE",
        "KALPAMANI_SHARADAR_SECRET_ID",
    }


def test_the_acquisition_path_imports_no_terraform_name_at_any_depth() -> None:
    """The import graph, separately from the call graph: nothing binds the name."""
    tree = ast.parse(ACQUIRE_SOURCE)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.update(alias.name for alias in node.names)
    assert "tf_outputs" not in imported
    assert "backend_settings" not in imported
    assert "TERRAFORM" not in imported
    assert "EXPECTED_PROFILE" not in imported


def test_the_governed_verifier_still_owns_the_state_read_for_other_callers() -> None:
    """``tf_outputs`` is not deleted -- foundation verification legitimately uses it.

    ADR-0023 removed one *caller*, and removing the function would have broken the
    foundation verifier this repository still runs under its own separate profile.
    """
    verifier = VERIFIER_PATH.read_text(encoding="utf-8")
    assert "def tf_outputs() -> dict[str, Any]:" in verifier
    assert "outputs = tf_outputs()" in verifier


# -- defense two: a runtime sentinel ------------------------------------------


class _TerraformSentinelTrippedError(Exception):
    """Raised by every trap below. Unique, so nothing else can be mistaken for it."""


class _SentinelSubprocess:
    """Stands in for the verifier's ``subprocess`` module and answers nothing."""

    @staticmethod
    def run(*_args: object, **_kwargs: object) -> object:
        raise _TerraformSentinelTrippedError("a subprocess was spawned")

    @staticmethod
    def Popen(*_args: object, **_kwargs: object) -> object:  # noqa: N802 - the real name
        raise _TerraformSentinelTrippedError("a subprocess was spawned")


def _armed_verifier(monkeypatch: pytest.MonkeyPatch) -> Any:
    """The real verifier, with the Terraform surface replaced by traps.

    Registered under its production name, so the entry point's own
    ``from aws_foundation_verify import ...`` resolves to this armed instance rather
    than to a stub written for the occasion.
    """
    spec = importlib.util.spec_from_file_location("aws_foundation_verify", VERIFIER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered *before* execution: the verifier declares dataclasses, and
    # ``dataclasses`` resolves an annotation through ``sys.modules[cls.__module__]``
    # while the class body runs.
    monkeypatch.setitem(sys.modules, "aws_foundation_verify", module)
    spec.loader.exec_module(module)

    def _trip(*_args: object, **_kwargs: object) -> object:
        raise _TerraformSentinelTrippedError("Terraform was reached")

    monkeypatch.setattr(module, "tf_outputs", _trip)
    monkeypatch.setattr(module, "backend_settings", _trip)
    monkeypatch.setattr(module, "subprocess", _SentinelSubprocess())
    # The real one parses the git-ignored local variables file. Replaced so no test
    # reads it, and so the account this suite compares against is a synthetic one.
    monkeypatch.setattr(module, "expected_account", lambda: ACCOUNT)
    return module


def _armed_binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A hardened synthetic private binding, inside a synthetic private root."""
    root = tmp_path / "KalpaMani" / "private"
    root.mkdir(parents=True, exist_ok=True)
    target = root / "binding.json"
    target.write_text(
        json.dumps(
            {
                "schema_version": rb.RUNTIME_BINDING_SCHEMA_VERSION,
                "binding_kind": rb.RUNTIME_BINDING_KIND,
                "contract_id": rb.RUNTIME_BINDING_CONTRACT_ID,
                "aws_partition": rb.EXPECTED_PARTITION,
                "aws_region": rb.EXPECTED_REGION,
                "target_account_id": ACCOUNT,
                "acquisition_profile": rb.EXPECTED_ACQUISITION_PROFILE,
                "licensed_bucket_name": BUCKET,
                "provenance": {
                    "implementation_commit": COMMIT,
                    "implementation_tree": TREE,
                    "environment_binding_sha256": ENVELOPE,
                },
            }
        ),
        encoding="utf-8",
    )
    hardened = rb.FileSecurity(
        current_principal=CURRENT,
        owner=CURRENT,
        inheritance_disabled=True,
        allow_principals=(CURRENT,),
        deny_principals=(),
    )
    monkeypatch.setattr(rb, "private_root", lambda: root)
    monkeypatch.setattr(rb, "windows_file_security", lambda _path: hardened)
    monkeypatch.setenv(rb.RUNTIME_BINDING_ENV_VAR, str(target))
    return target


def _acquire_module() -> Any:
    """The entry point, loaded by path exactly as the other operator tests load one."""
    spec = importlib.util.spec_from_file_location("adr0023_acquisition_entry_point", ACQUIRE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_sentinel_fires_when_terraform_is_actually_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The trap is armed -- proven by tripping it deliberately.

    Without this, "the sentinel never fired" would be indistinguishable from "the
    sentinel was never installed".
    """
    verifier = _armed_verifier(monkeypatch)
    with pytest.raises(_TerraformSentinelTrippedError):
        verifier.tf_outputs()
    with pytest.raises(_TerraformSentinelTrippedError):
        verifier.subprocess.run(["anything"])


def test_stage_six_resolves_the_bucket_without_tripping_the_sentinel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real stage-6 resolver, against a real file, with Terraform trapped."""
    _armed_verifier(monkeypatch)
    _armed_binding(tmp_path, monkeypatch)
    acquire = _acquire_module()
    assert acquire._governed_licensed_bucket() == BUCKET


def test_stage_six_refuses_when_the_binding_is_absent_without_tripping_the_sentinel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _armed_verifier(monkeypatch)
    _armed_binding(tmp_path, monkeypatch)
    monkeypatch.delenv(rb.RUNTIME_BINDING_ENV_VAR, raising=False)
    acquire = _acquire_module()
    with pytest.raises(rb.RuntimeBindingError) as caught:
        acquire._governed_licensed_bucket()
    assert caught.value.defect is rb.RuntimeBindingDefect.ENVIRONMENT_UNSET


# -- the stage, in the run it belongs to --------------------------------------


def _run(acquire: Any, **overrides: Any) -> Any:
    """Drive the acquisition run with fakes everywhere except the stage under test."""
    arguments: dict[str, Any] = {
        "authorization": acquire._EMPIRICAL_AUTHORIZATION,
        "execution_id": "synthetic-adr0023-a",
        "env": {},
        "modules": {},
        "load_inventory": lambda: None,
        "profile_of": lambda: acquire.EXPECTED_PROFILE,
        "identity_gate": lambda: None,
        "resolve_licensed_bucket": acquire._governed_licensed_bucket,
        "secret_id_source": lambda: "x",
        "secrets_client_factory": lambda: None,
        "s3_client_factory": lambda: None,
        "transport_factory": lambda: None,
        "clock": None,
        "monotonic": lambda: 0.0,
        "sleeper": lambda _seconds: None,
    }
    arguments.update(overrides)
    return acquire.run_empirical_qualification(**arguments)


def test_a_valid_binding_carries_the_run_past_stage_six(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stage 6 passes and stage 7 is entered -- the defect's exact inverse.

    Before ADR-0023 this run refused at stage 6 every time, so the marker below is
    the whole repair: the secret-identifier source is reached.
    """
    _armed_verifier(monkeypatch)
    _armed_binding(tmp_path, monkeypatch)
    acquire = _acquire_module()
    reached: list[str] = []

    def _secret_id() -> str:
        reached.append("stage 7")
        raise LookupError("stopped here on purpose, before anything private")

    with pytest.raises(acquire.EmpiricalQualificationError) as raised:
        _run(acquire, secret_id_source=_secret_id)
    assert reached == ["stage 7"]
    assert raised.value.outcome is acquire.EmpiricalOutcome.REFUSED_SECRET_IDENTIFIER


BINDING_REFUSALS: Final[tuple[tuple[str, str | None], ...]] = (
    ("the variable is unset", None),
    ("the path is relative", "binding.json"),
    ("the path is outside the private root", r"C:\elsewhere\binding.json"),
)


@pytest.mark.parametrize(
    "selected",
    [selected for _label, selected in BINDING_REFUSALS],
    ids=[label for label, _selected in BINDING_REFUSALS],
)
def test_a_missing_or_unsafe_binding_refuses_with_the_closed_bucket_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, selected: str | None
) -> None:
    """One public outcome and one exit code, whatever the private reason was."""
    _armed_verifier(monkeypatch)
    _armed_binding(tmp_path, monkeypatch)
    if selected is None:
        monkeypatch.delenv(rb.RUNTIME_BINDING_ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(rb.RUNTIME_BINDING_ENV_VAR, selected)
    acquire = _acquire_module()
    reached: list[str] = []

    def _secret_id() -> str:
        reached.append("stage 7")
        return "x"

    with pytest.raises(acquire.EmpiricalQualificationError) as raised:
        _run(acquire, secret_id_source=_secret_id)
    assert raised.value.outcome is acquire.EmpiricalOutcome.REFUSED_LICENSED_BUCKET
    assert acquire.EXIT_STATUS[raised.value.outcome] == 8
    assert reached == []


def test_the_bucket_refusal_says_nothing_the_private_binding_knew(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _armed_verifier(monkeypatch)
    target = _armed_binding(tmp_path, monkeypatch)
    monkeypatch.setenv(rb.RUNTIME_BINDING_ENV_VAR, r"C:\elsewhere\binding.json")
    acquire = _acquire_module()
    with pytest.raises(acquire.EmpiricalQualificationError) as raised:
        _run(acquire)
    printed = capsys.readouterr()
    for surface in (str(raised.value), repr(raised.value), printed.out, printed.err):
        for canary in (ACCOUNT, BUCKET, CURRENT, COMMIT, TREE, ENVELOPE, str(target)):
            assert canary not in surface
        assert "PATH_OUTSIDE_PRIVATE_ROOT" not in surface
        assert "ENVIRONMENT_UNSET" not in surface


def test_the_run_still_requires_its_own_authorization_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0023 changed one stage. It did not open the gate in front of them."""
    _armed_verifier(monkeypatch)
    _armed_binding(tmp_path, monkeypatch)
    acquire = _acquire_module()
    with pytest.raises(acquire.EmpiricalQualificationError) as raised:
        _run(acquire, authorization=object())
    assert raised.value.outcome is acquire.EmpiricalOutcome.REFUSED_NOT_AUTHORIZED
    assert acquire.main([]) == acquire.EXIT_STATUS[acquire.EmpiricalOutcome.REFUSED_NOT_AUTHORIZED]


def test_the_two_authorization_flags_remain_distinct() -> None:
    assess_source = (SCRIPTS / "sharadar_qualification_assessment.py").read_text(encoding="utf-8")
    acquire = _acquire_module()
    assert acquire.AUTHORIZATION_FLAG not in assess_source
    assert "--i-am-the-operator-authorizing-qualification-assessment" not in ACQUIRE_SOURCE


# -- the guards fail when the defect comes back -------------------------------

_RESOLVER = re.compile(
    r"^def _governed_licensed_bucket\(\) -> str:\n(?:.*\n)*?(?=^def |\Z)",
    re.MULTILINE,
)


def _mutated(replacement: str) -> str:
    """The entry point with its bucket resolver replaced. **In memory only.**"""
    assert len(_RESOLVER.findall(ACQUIRE_SOURCE)) == 1
    return _RESOLVER.sub(replacement, ACQUIRE_SOURCE, count=1)


DIRECT_REINTRODUCTION: Final = '''def _governed_licensed_bucket() -> str:
    """The licensed bucket from governed Terraform state."""
    from aws_foundation_verify import tf_outputs

    return str(tf_outputs()["licensed_bucket_name"])


'''

ALIASED_REINTRODUCTION: Final = '''def _wrapped_outputs() -> dict:
    """A wrapper, so the forbidden name never appears at the call site."""
    from aws_foundation_verify import tf_outputs as _outputs

    return _outputs()


def _governed_licensed_bucket() -> str:
    """The licensed bucket, one indirection away from the state read."""
    return str(_wrapped_outputs()["licensed_bucket_name"])


'''

FOUNDATION_PROFILE_FALLBACK: Final = '''def _governed_licensed_bucket() -> str:
    """The licensed bucket, resolved by falling back to the foundation profile."""
    import os

    from aws_foundation_verify import EXPECTED_PROFILE

    os.environ["AWS_PROFILE"] = EXPECTED_PROFILE
    from kalpamani.data.qualify.sharadar.runtime_binding import load_runtime_binding

    return load_runtime_binding(expected_account="000000000000").licensed_bucket_name


'''

RAW_ENVIRONMENT_BYPASS: Final = '''def _governed_licensed_bucket() -> str:
    """The licensed bucket, straight out of an unvalidated environment variable."""
    import os

    return os.environ["KALPAMANI_LICENSED_BUCKET"]


'''


def test_the_mutation_helper_actually_replaces_the_resolver() -> None:
    """A mutation that silently changed nothing would make every test below pass."""
    mutated = _mutated(DIRECT_REINTRODUCTION)
    assert mutated != ACQUIRE_SOURCE
    assert "load_runtime_binding" not in _RESOLVER.findall(mutated)[0]
    ast.parse(mutated)


def test_the_call_graph_catches_a_direct_reintroduction() -> None:
    findings = _terraform_findings(_mutated(DIRECT_REINTRODUCTION))
    assert "the Terraform state read is reachable" in findings
    assert "the pinned Terraform executable is reachable" in findings
    assert "the private runtime binding loader is not reachable" in findings


def test_the_call_graph_catches_a_reintroduction_behind_an_alias() -> None:
    """The exact case the old source-string guard could never have seen."""
    mutated = _mutated(ALIASED_REINTRODUCTION)
    assert "tf_outputs()" not in _RESOLVER.findall(mutated)[0]
    findings = _terraform_findings(mutated)
    assert "the Terraform state read is reachable" in findings
    assert "the pinned Terraform executable is reachable" in findings


def test_the_call_graph_catches_a_fallback_to_the_foundation_profile() -> None:
    findings = _terraform_findings(_mutated(FOUNDATION_PROFILE_FALLBACK))
    assert "the shared foundation profile is reachable" in findings


def test_the_guards_catch_a_raw_bucket_environment_variable() -> None:
    """The file contract exists so nobody can name a licensed destination inline."""
    mutated = _mutated(RAW_ENVIRONMENT_BYPASS)
    assert _terraform_findings(mutated) == ["the private runtime binding loader is not reachable"]
    assert "KALPAMANI_LICENSED_BUCKET" in _environment_names(mutated)
    assert _environment_names(mutated) != {"AWS_PROFILE", "KALPAMANI_SHARADAR_SECRET_ID"}


def test_the_repository_source_is_unchanged_by_any_mutation() -> None:
    """Every mutation above is a string. The file on disk is never rewritten."""
    assert ACQUIRE_PATH.read_text(encoding="utf-8") == ACQUIRE_SOURCE
    assert "tf_outputs" not in ACQUIRE_SOURCE
