"""Terraform is unreachable from the combined assessment path (ADR-0025).

The acquisition path got this treatment when ADR-0023 corrected it, and the assessment
path was explicitly left out of that scope. It had **two** prohibited dependencies
rather than one, and they fail differently, so both are watched here:

1. ``tf_outputs`` -- a Terraform child process, attempted under an actor with no grant
   on the state bucket. It could not have succeeded.
2. ``expected_account`` -- a plain read of the local, git-ignored Terraform variables
   file, reached through the account-finding identity gate. It *worked*, which is why a
   bucket-only correction would have looked finished while leaving a governed identity
   check depending on a Terraform input.

Three independent defenses, because any one alone can be argued around:

**A name-level call graph.** Every top-level definition of the assessment entry point is
walked, every name it references is resolved through that module's own import bindings
into the defining module, and the walk repeats. Reaching ``aws_foundation_verify`` is not
enough to condemn the path -- the identity gate legitimately lives there -- so the graph
is followed *per name*, and the question is whether the forbidden names are in the
closure.

**A runtime sentinel.** The real verifier module is loaded, its Terraform surface,
``subprocess`` and ``expected_account`` are replaced with traps, and the corrected
binding-resolution and identity stages are then run for real against synthetic inputs. A
trap that never fires while the stages succeed is evidence the static answer describes
what actually happens.

**Mutation.** Both dependencies are reintroduced in memory -- directly, behind an alias,
through the foundation profile, through a raw environment variable, and through the
account-finding gate -- and each guard is watched failing. A guard nobody has watched
fail is a guard nobody has tested. **No production file is rewritten by any of it.**

Every identifier here is invented. No real account, bucket, path, principal or
deployment value appears, and no real private artifact is created or read.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pytest

from kalpamani.data.qualify.sharadar import runtime_binding as rb

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
SRC = REPO_ROOT / "src"
ASSESS_PATH = SCRIPTS / "sharadar_qualification_assessment.py"
VERIFIER_PATH = SCRIPTS / "aws_foundation_verify.py"

ASSESS_KEY: Final = "scripts:sharadar_qualification_assessment"
VERIFIER_KEY: Final = "scripts:aws_foundation_verify"
BINDING_KEY: Final = "src:kalpamani.data.qualify.sharadar.runtime_binding"
ASSESSMENT_KEY: Final = "src:kalpamani.data.qualify.sharadar.assessment"

#: The four operator tools the assessment path must not be able to reach. The capture
#: is the one thing in this repository that may read the governed infrastructure
#: outputs, so reaching it would put Terraform back in the closure by a route the
#: Terraform checks are not looking at; the two materialization gates create the
#: private artifacts, and a run that could reach either could manufacture the
#: configuration it is supposed to be handed.
CAPTURE_KEY: Final = "scripts:qualification_environment_binding_capture"
MATERIALIZE_KEY: Final = "scripts:qualification_runtime_binding_materialize"
ASSESSMENT_MATERIALIZE_KEY: Final = "scripts:qualification_assessment_binding_materialize"
WRITER_KEY: Final = "scripts:qualification_private_artifacts"

#: The module-level statements, gathered under one pseudo-name so they are walked
#: alongside the real definitions.
MODULE_BODY: Final = "<module>"

ASSESS_SOURCE: Final = ASSESS_PATH.read_text(encoding="utf-8")

#: Synthetic, and matching no deployment. Reused by the sentinel and the integration
#: tests below.
ACCOUNT: Final = "000000000000"
OTHER_ACCOUNT: Final = "999999999999"
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
    *do*. A docstring explaining that Terraform is no longer reached would otherwise be
    indistinguishable from an argv naming the executable.
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
    """Everything the assessment path can reach, and every literal it can see."""

    definitions: frozenset[Definition]
    literals: frozenset[str]


def _reachability(entry_source: str) -> Reachability:
    """The transitive, name-level closure of the assessment entry point."""
    sources: dict[str, str] = {ASSESS_KEY: entry_source}
    analyses: dict[str, _Analysis] = {}

    def analysis_of(key: str, path: Path | None) -> _Analysis:
        if key not in analyses:
            if key not in sources:
                assert path is not None
                sources[key] = path.read_text(encoding="utf-8")
            analyses[key] = _analyse(key, sources[key])
        return analyses[key]

    entry = analysis_of(ASSESS_KEY, ASSESS_PATH)
    pending: list[Definition] = [(ASSESS_KEY, name) for name in entry.definitions]
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


#: Definitions the assessment path must never reach. Each is a real name in the
#: governed verifier, so a miss here is a miss about something that exists rather than
#: about a name nobody wrote.
#:
#: ``expected_account`` and ``TFVARS`` are the half of this defect a bucket-only
#: correction would have left in place, and ``qualification_identity_gate`` is the
#: route back to them: the account-finding gate calls it, so admitting that gate would
#: readmit the Terraform input without naming it.
FORBIDDEN: Final[tuple[tuple[Definition, str], ...]] = (
    ((VERIFIER_KEY, "tf_outputs"), "the Terraform state read"),
    ((VERIFIER_KEY, "TERRAFORM"), "the pinned Terraform executable"),
    ((VERIFIER_KEY, "backend_settings"), "the Terraform backend configuration"),
    ((VERIFIER_KEY, "BACKEND_HCL"), "the backend configuration file"),
    ((VERIFIER_KEY, "check_state_backend"), "the state-bucket S3 read"),
    ((VERIFIER_KEY, "EXPECTED_PROFILE"), "the shared foundation profile"),
    ((VERIFIER_KEY, "expected_account"), "the private Terraform account input"),
    ((VERIFIER_KEY, "TFVARS"), "the local Terraform variables file"),
    ((VERIFIER_KEY, "INFRA"), "the Terraform configuration directory"),
    ((VERIFIER_KEY, "qualification_identity_gate"), "the account-finding identity gate"),
)


def _mentions_terraform(literal: str) -> bool:
    """Whether a literal names Terraform, for any reason at all.

    **Unlike the acquisition guard, nothing is permitted here.** That one exempts
    ``terraform.tfvars`` because the acquisition path legitimately reads it and the
    gate's own refusal message names it in prose. This path may reach neither, so the
    exemption would be a hole in exactly the place this decision closes.
    """
    return "terraform" in literal.lower()


def _terraform_findings(entry_source: str) -> list[str]:
    """Every way this assessment path could reach Terraform. Empty when it cannot."""
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
    if (BINDING_KEY, "load_assessment_runtime_binding") not in reach.definitions:
        findings.append("the private assessment binding loader is not reachable")
    if (VERIFIER_KEY, "qualification_identity_gate_for") not in reach.definitions:
        findings.append("the actor-bound identity gate is not reachable")
    return findings


#: Every operator tool the assessment path must not be able to reach, and what to call
#: it in a finding. Each is a real module.
OPERATOR_TOOLS: Final[tuple[tuple[str, str], ...]] = (
    (CAPTURE_KEY, "the environment-binding capture"),
    (MATERIALIZE_KEY, "the runtime-binding materialization gate"),
    (ASSESSMENT_MATERIALIZE_KEY, "the assessment-binding materialization gate"),
    (WRITER_KEY, "the private-artifact writer"),
)


def _operator_tool_findings(entry_source: str) -> list[str]:
    """Every operator tool this assessment path could reach. Empty when it cannot.

    Kept separate from :func:`_terraform_findings` rather than folded into it: the
    Terraform findings are asserted exactly in places below, and a check that grew a
    new member would change what those assertions mean.
    """
    reached = {key for key, _name in _reachability(entry_source).definitions}
    return [f"{description} is reachable" for key, description in OPERATOR_TOOLS if key in reached]


#: Names that would give this process a credential or a provider. It has never had
#: either, and a correction that removed a Terraform dependency must not add one.
FORBIDDEN_CAPABILITIES: Final[tuple[tuple[Definition, str], ...]] = (
    ((BINDING_KEY, "load_environment_binding"), "the environment-binding loader"),
    ((BINDING_KEY, "parse_environment_binding"), "the environment-binding validator"),
    ((BINDING_KEY, "require_exclusive_security"), "the writer's access-control policy hook"),
)


def _capability_findings(entry_source: str) -> list[str]:
    """Every capability-widening name this assessment path could reach."""
    reach = _reachability(entry_source)
    return [
        f"{description} is reachable"
        for definition, description in FORBIDDEN_CAPABILITIES
        if definition in reach.definitions
    ]


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


def test_the_call_graph_reaches_into_the_governed_verifier_and_the_loader() -> None:
    """Positive controls, so a negative result below means something.

    An analyzer that resolved nothing would report every forbidden name absent and look
    like a passing guard. These prove it crosses the module boundary, then a second hop
    *inside* the verifier, and then into the loader and the combined assessment under
    ``src/``.
    """
    reach = _reachability(ASSESS_SOURCE)
    for control in (
        (VERIFIER_KEY, "qualification_identity_gate_for"),
        (VERIFIER_KEY, "qualification_identity_refusal"),
        (VERIFIER_KEY, "_run_aws"),
        (VERIFIER_KEY, "parse_assumed_role_arn"),
        (BINDING_KEY, "load_assessment_runtime_binding"),
        (BINDING_KEY, "parse_assessment_runtime_binding"),
        (BINDING_KEY, "windows_file_security"),
        (ASSESSMENT_KEY, "run_combined_assessment"),
    ):
        assert control in reach.definitions, control


def test_the_call_graph_sees_string_literals_from_reached_modules() -> None:
    """A second control, for the literal scan the Terraform check also relies on."""
    reach = _reachability(ASSESS_SOURCE)
    assert "sts" in reach.literals
    assert "kalpamani-qualification-assessment" in reach.literals


def test_the_forbidden_names_all_exist_in_the_verifier() -> None:
    """A guard aimed at names nobody wrote would pass by accident."""
    verifier = _analyse(VERIFIER_KEY, VERIFIER_PATH.read_text(encoding="utf-8"))
    for (key, name), description in FORBIDDEN:
        assert key == VERIFIER_KEY, description
        assert name in verifier.definitions, name


def test_the_operator_tools_exist_where_the_guard_looks_for_them() -> None:
    for key, _description in OPERATOR_TOOLS:
        located = _module_file(key.split(":", 1)[1])
        assert located is not None, key
        assert located[0] == key


# -- defense one: the assessment path cannot reach Terraform ------------------


def test_the_assessment_path_cannot_reach_terraform_or_its_private_input() -> None:
    assert _terraform_findings(ASSESS_SOURCE) == []


def test_the_assessment_path_reads_exactly_one_environment_name() -> None:
    """The governed profile, and nothing else. **No bucket, and no account.**

    The private binding path is read by the loader under ``src/`` rather than here,
    exactly as the acquisition entry point delegates its own -- so the entry point
    *declares* the variable name, to state its operator contract, and never looks it
    up. Both halves matter: a bucket or an account name appearing in this set would be
    the raw-environment bypass the file contract exists to prevent.
    """
    assert _environment_names(ASSESS_SOURCE) == {"AWS_PROFILE"}
    module = SRC / "kalpamani" / "data" / "qualify" / "sharadar" / "runtime_binding.py"
    quoted = f'"{rb.ASSESSMENT_RUNTIME_BINDING_ENV_VAR}"'
    for surface in (ASSESS_SOURCE, module.read_text(encoding="utf-8")):
        assert "ASSESSMENT_RUNTIME_BINDING_ENV_VAR: Final = (" in surface
        assert quoted in surface
    # And the acquisition variable is not among them, in either direction: two actors
    # reading one name would be the shared artifact this contract exists to avoid.
    assert rb.RUNTIME_BINDING_ENV_VAR not in ASSESS_SOURCE
    # Distinctness through a set rather than an inequality: both constants are
    # literal-typed, so a direct ``!=`` is a comparison the type checker decides and
    # refuses as non-overlapping. The set asks the same question at runtime.
    names: set[str] = {rb.ASSESSMENT_RUNTIME_BINDING_ENV_VAR, rb.RUNTIME_BINDING_ENV_VAR}
    assert len(names) == 2


def test_the_assessment_path_imports_no_terraform_name_at_any_depth() -> None:
    """The import graph, separately from the call graph: nothing binds the name."""
    imported: set[str] = set()
    for node in ast.walk(ast.parse(ASSESS_SOURCE)):
        if isinstance(node, ast.ImportFrom):
            imported.update(alias.name for alias in node.names)
    for forbidden in (
        "tf_outputs",
        "backend_settings",
        "TERRAFORM",
        "EXPECTED_PROFILE",
        "expected_account",
        "qualification_identity_gate",
    ):
        assert forbidden not in imported, forbidden


def test_the_assessment_path_cannot_reach_any_operator_tool() -> None:
    """Materialization is somebody's separately authorized action, not a run's."""
    assert _operator_tool_findings(ASSESS_SOURCE) == []


def test_the_assessment_path_cannot_reach_a_credential_or_a_provider() -> None:
    """Removing a Terraform dependency did not add a capability."""
    assert _capability_findings(ASSESS_SOURCE) == []
    reach = _reachability(ASSESS_SOURCE)
    for name in ("SharadarCredential", "UrllibTransport", "get_secret_value"):
        assert not [definition for definition in reach.definitions if definition[1] == name], name
    for literal in reach.literals:
        assert "secretsmanager" not in literal
        assert "get_secret_value" not in literal


def test_the_assessment_path_cannot_reach_the_acquisition_binding_loader() -> None:
    """Two artifacts, two loaders. Neither actor may resolve the other's file."""
    reach = _reachability(ASSESS_SOURCE)
    assert (BINDING_KEY, "load_runtime_binding") not in reach.definitions
    assert (BINDING_KEY, "environment_binding_path") not in reach.definitions
    assert (BINDING_KEY, "load_assessment_runtime_binding") in reach.definitions
    assert (BINDING_KEY, "assessment_runtime_binding_path") in reach.definitions


def test_the_governed_verifier_still_owns_the_state_read_for_other_callers() -> None:
    """``tf_outputs`` and ``expected_account`` are not deleted -- others still need them.

    ADR-0025 removed callers. Removing either function would have broken the foundation
    verifier this repository still runs under its own separate profile, and the
    acquisition path that legitimately reads the local account binding.
    """
    verifier = VERIFIER_PATH.read_text(encoding="utf-8")
    assert "def tf_outputs() -> dict[str, Any]:" in verifier
    assert "outputs = tf_outputs()" in verifier
    assert "def expected_account() -> str | None:" in verifier
    acquire = (SCRIPTS / "sharadar_empirical_qualification.py").read_text(encoding="utf-8")
    assert "expected_account" in acquire


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


def _armed_verifier(monkeypatch: pytest.MonkeyPatch, *, identity: Any = None) -> Any:
    """The real verifier, with Terraform **and the Terraform input** replaced by traps.

    Registered under its production name, so the entry point's own
    ``from aws_foundation_verify import ...`` resolves to this armed instance rather
    than to a stub written for the occasion.

    ``expected_account`` is a trap here rather than a synthetic value, which is the one
    place this differs from the acquisition sentinel: the acquisition path is *supposed*
    to call it, and this path is supposed to be unable to.
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
        raise _TerraformSentinelTrippedError("Terraform or its private input was reached")

    monkeypatch.setattr(module, "tf_outputs", _trip)
    monkeypatch.setattr(module, "backend_settings", _trip)
    monkeypatch.setattr(module, "expected_account", _trip)
    monkeypatch.setattr(module, "subprocess", _SentinelSubprocess())

    recorded: list[Any] = []

    def _caller_identity() -> Any:
        recorded.append("sts")
        return module.AwsOutcome(ok=True, data=identity, code="")

    monkeypatch.setattr(module, "_run_aws", lambda _args: _caller_identity())
    # Attached rather than returned separately, so the sentinel and its counter travel
    # together. ``setattr`` on the module object rather than an assignment, because a
    # module has no declared attribute of this name for a type checker to accept.
    setattr(module, "recorded_identity_calls", recorded)  # noqa: B010
    return module


def _assessment_document(**overrides: Any) -> dict[str, Any]:
    """A well-formed synthetic assessment binding, built from production constants."""
    document: dict[str, Any] = {
        "schema_version": rb.ASSESSMENT_RUNTIME_BINDING_SCHEMA_VERSION,
        "binding_kind": rb.ASSESSMENT_RUNTIME_BINDING_KIND,
        "contract_id": rb.ASSESSMENT_RUNTIME_BINDING_CONTRACT_ID,
        "aws_partition": rb.EXPECTED_PARTITION,
        "aws_region": rb.EXPECTED_REGION,
        "target_account_id": ACCOUNT,
        "assessment_profile": rb.EXPECTED_ASSESSMENT_PROFILE,
        "licensed_bucket_name": BUCKET,
        "provenance": {
            "implementation_commit": COMMIT,
            "implementation_tree": TREE,
            "environment_binding_sha256": ENVELOPE,
        },
    }
    document.update(overrides)
    return document


def _armed_binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> Path:
    """A hardened synthetic private binding, inside a synthetic private root."""
    root = tmp_path / "KalpaMani" / "private"
    root.mkdir(parents=True, exist_ok=True)
    target = root / "assessment.json"
    target.write_text(json.dumps(_assessment_document(**overrides)), encoding="utf-8")
    hardened = rb.FileSecurity(
        current_principal=CURRENT,
        owner=CURRENT,
        inheritance_disabled=True,
        allow_principals=(CURRENT,),
        deny_principals=(),
    )
    monkeypatch.setattr(rb, "private_root", lambda: root)
    monkeypatch.setattr(rb, "windows_file_security", lambda _path: hardened)
    monkeypatch.setenv(rb.ASSESSMENT_RUNTIME_BINDING_ENV_VAR, str(target))
    return target


def _assess_module() -> Any:
    """The entry point, loaded by path exactly as the other operator tests load one."""
    spec = importlib.util.spec_from_file_location("adr0025_assessment_entry_point", ASSESS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _assumed_role(account: str = ACCOUNT, *, actor: str = "Assessment") -> dict[str, str]:
    """A synthetic ``sts:GetCallerIdentity`` response for one governed actor."""
    role = f"AWSReservedSSO_KalpaManiQualification{actor}_0123abcd"
    return {
        "UserId": "AROASYNTHETIC:operator",
        "Account": account,
        "Arn": f"arn:aws:sts::{account}:assumed-role/{role}/operator",
    }


def test_the_sentinel_fires_when_terraform_or_its_input_is_actually_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The traps are armed -- proven by tripping them deliberately.

    Without this, "the sentinel never fired" would be indistinguishable from "the
    sentinel was never installed".
    """
    verifier = _armed_verifier(monkeypatch)
    for reach in (verifier.tf_outputs, verifier.backend_settings, verifier.expected_account):
        with pytest.raises(_TerraformSentinelTrippedError):
            reach()
    with pytest.raises(_TerraformSentinelTrippedError):
        verifier.subprocess.run(["anything"])


def test_stage_four_resolves_the_binding_without_tripping_the_sentinel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real stage-4 resolver, against a real file, with Terraform trapped."""
    _armed_verifier(monkeypatch)
    _armed_binding(tmp_path, monkeypatch)
    assess = _assess_module()
    binding = assess._assessment_runtime_binding()
    assert binding.licensed_bucket_name == BUCKET
    assert binding.target_account_id == ACCOUNT
    assert binding.assessment_profile == "kalpamani-qualification-assessment"


def test_stage_four_refuses_when_the_binding_is_absent_without_tripping_the_sentinel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _armed_verifier(monkeypatch)
    _armed_binding(tmp_path, monkeypatch)
    monkeypatch.delenv(rb.ASSESSMENT_RUNTIME_BINDING_ENV_VAR, raising=False)
    assess = _assess_module()
    with pytest.raises(rb.RuntimeBindingError) as caught:
        assess._assessment_runtime_binding()
    assert caught.value.defect is rb.RuntimeBindingDefect.ENVIRONMENT_UNSET


def test_stage_five_compares_the_bound_account_without_tripping_the_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One identity call, against the account the caller supplied. No Terraform input."""
    verifier = _armed_verifier(monkeypatch, identity=_assumed_role())
    monkeypatch.setenv("AWS_PROFILE", "kalpamani-qualification-assessment")
    assess = _assess_module()
    assert assess._governed_identity_gate(ACCOUNT) is None
    assert verifier.recorded_identity_calls == ["sts"]


def test_stage_five_refuses_an_identity_in_another_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _armed_verifier(monkeypatch, identity=_assumed_role(OTHER_ACCOUNT))
    monkeypatch.setenv("AWS_PROFILE", "kalpamani-qualification-assessment")
    assess = _assess_module()
    assert assess._governed_identity_gate(ACCOUNT) is not None


def test_stage_five_refuses_the_acquisition_role(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other actor's credential is refused before any licensed object is read."""
    _armed_verifier(monkeypatch, identity=_assumed_role(actor="Acquire"))
    monkeypatch.setenv("AWS_PROFILE", "kalpamani-qualification-assessment")
    assess = _assess_module()
    assert assess._governed_identity_gate(ACCOUNT) is not None


# -- the stages, in the run they belong to ------------------------------------


def _run(assess: Any, **overrides: Any) -> Any:
    """Drive the assessment with fakes everywhere except the stages under test."""
    arguments: dict[str, Any] = {
        "authorization": assess._ASSESSMENT_AUTHORIZATION,
        "run_a_execution_id": "synthetic-adr0025-a",
        "run_b_execution_id": "synthetic-adr0025-b",
        "assessment_id": "synthetic-adr0025-assessment",
        "env": {},
        "modules": {},
        "profile_of": lambda: assess.EXPECTED_PROFILE,
        "load_binding": assess._assessment_runtime_binding,
        "identity_gate": lambda _account: None,
        "s3_client_factory": lambda: None,
        "clock": None,
    }
    arguments.update(overrides)
    return assess.run_qualification_assessment(**arguments)


def test_a_valid_binding_carries_the_run_past_stage_five(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stages 4 and 5 pass and stage 7 is entered -- the defect's exact inverse.

    Before this correction the run refused at the Terraform-backed bucket stage every
    time, so the marker below is the whole repair: the S3 client factory is reached.
    """
    _armed_verifier(monkeypatch)
    _armed_binding(tmp_path, monkeypatch)
    assess = _assess_module()
    reached: list[str] = []

    def _client() -> Any:
        reached.append("stage 7")
        raise LookupError("stopped here on purpose, before anything private")

    with pytest.raises(assess.QualificationAssessmentError) as raised:
        _run(assess, s3_client_factory=_client)
    assert reached == ["stage 7"]
    assert raised.value.outcome is assess.AssessmentOutcome.REFUSED_DEPENDENCY


def test_the_binding_supplies_the_account_the_identity_gate_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate is handed the bound account, and not one it went looking for."""
    _armed_verifier(monkeypatch)
    _armed_binding(tmp_path, monkeypatch)
    assess = _assess_module()
    supplied: list[str] = []

    def _gate(account: str) -> str | None:
        supplied.append(account)
        return None

    with pytest.raises(assess.QualificationAssessmentError):
        _run(assess, identity_gate=_gate, s3_client_factory=lambda: 1 / 0)
    assert supplied == [ACCOUNT]


def test_the_binding_is_loaded_before_the_identity_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Order is the security property, and here it is also an arithmetic necessity."""
    _armed_verifier(monkeypatch)
    _armed_binding(tmp_path, monkeypatch)
    assess = _assess_module()
    order: list[str] = []

    def _load() -> Any:
        order.append("binding")
        return assess._assessment_runtime_binding()

    def _gate(_account: str) -> str | None:
        order.append("identity")
        return "refused"

    with pytest.raises(assess.QualificationAssessmentError) as raised:
        _run(assess, load_binding=_load, identity_gate=_gate)
    assert order == ["binding", "identity"]
    assert raised.value.outcome is assess.AssessmentOutcome.REFUSED_IDENTITY


BINDING_REFUSALS: Final[tuple[tuple[str, str | None], ...]] = (
    ("the variable is unset", None),
    ("the path is relative", "assessment.json"),
    ("the path is outside the private root", r"C:\elsewhere\assessment.json"),
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
        monkeypatch.delenv(rb.ASSESSMENT_RUNTIME_BINDING_ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(rb.ASSESSMENT_RUNTIME_BINDING_ENV_VAR, selected)
    assess = _assess_module()
    reached: list[str] = []

    def _gate(_account: str) -> str | None:
        reached.append("stage 5")
        return None

    with pytest.raises(assess.QualificationAssessmentError) as raised:
        _run(assess, identity_gate=_gate)
    assert raised.value.outcome is assess.AssessmentOutcome.REFUSED_LICENSED_BUCKET
    assert assess.EXIT_STATUS[raised.value.outcome] == 6
    assert reached == []


def test_a_binding_carrying_another_actor_profile_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The acquisition profile in an assessment binding is a refusal, not a switch."""
    _armed_verifier(monkeypatch)
    _armed_binding(tmp_path, monkeypatch, assessment_profile=rb.EXPECTED_ACQUISITION_PROFILE)
    assess = _assess_module()
    with pytest.raises(assess.QualificationAssessmentError) as raised:
        _run(assess)
    assert raised.value.outcome is assess.AssessmentOutcome.REFUSED_LICENSED_BUCKET


def _recording_gate(reached: list[str]) -> Callable[[str], str | None]:
    """An identity gate that records that it was reached, and passes."""

    def _gate(_account: str) -> str | None:
        reached.append("stage 5")
        return None

    return _gate


def test_an_object_that_is_not_a_binding_refuses_before_the_identity_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A loader answering with the wrong shape is a licensed-configuration refusal."""
    _armed_verifier(monkeypatch)
    _armed_binding(tmp_path, monkeypatch)
    assess = _assess_module()
    reached: list[str] = []

    with pytest.raises(assess.QualificationAssessmentError) as raised:
        _run(
            assess,
            load_binding=lambda: object(),
            identity_gate=_recording_gate(reached),
        )
    assert raised.value.outcome is assess.AssessmentOutcome.REFUSED_LICENSED_BUCKET
    assert reached == []


def test_the_bucket_refusal_says_nothing_the_private_binding_knew(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _armed_verifier(monkeypatch)
    target = _armed_binding(tmp_path, monkeypatch)
    monkeypatch.setenv(rb.ASSESSMENT_RUNTIME_BINDING_ENV_VAR, r"C:\elsewhere\assessment.json")
    assess = _assess_module()
    with pytest.raises(assess.QualificationAssessmentError) as raised:
        _run(assess)
    printed = capsys.readouterr()
    for surface in (str(raised.value), repr(raised.value), printed.out, printed.err):
        for canary in (ACCOUNT, BUCKET, CURRENT, COMMIT, TREE, ENVELOPE, str(target)):
            assert canary not in surface
        assert "PATH_OUTSIDE_PRIVATE_ROOT" not in surface
        assert "ENVIRONMENT_UNSET" not in surface


def test_no_s3_client_is_constructed_when_the_identity_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A loaded binding is not a licence to build a client for the wrong actor."""
    _armed_verifier(monkeypatch)
    _armed_binding(tmp_path, monkeypatch)
    assess = _assess_module()
    constructed: list[str] = []

    with pytest.raises(assess.QualificationAssessmentError) as raised:
        _run(
            assess,
            identity_gate=lambda _account: "the identity did not match",
            s3_client_factory=lambda: constructed.append("client"),
        )
    assert raised.value.outcome is assess.AssessmentOutcome.REFUSED_IDENTITY
    assert constructed == []


def test_the_run_still_requires_its_own_authorization_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0025 changed two stages. It did not open the gate in front of them."""
    _armed_verifier(monkeypatch)
    _armed_binding(tmp_path, monkeypatch)
    assess = _assess_module()
    with pytest.raises(assess.QualificationAssessmentError) as raised:
        _run(assess, authorization=object())
    assert raised.value.outcome is assess.AssessmentOutcome.REFUSED_NOT_AUTHORIZED
    assert assess.main([]) == assess.EXIT_STATUS[assess.AssessmentOutcome.REFUSED_NOT_AUTHORIZED]


def test_an_ordinary_import_reads_no_assessment_binding_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Importing the module looks nothing up, the new variable included."""
    seen: list[str] = []
    import os as _os

    real_get = _os.environ.get

    def _watched(key: str, default: Any = None) -> Any:
        seen.append(key)
        return real_get(key, default)

    monkeypatch.setattr(_os.environ, "get", _watched)
    _assess_module()
    assert rb.ASSESSMENT_RUNTIME_BINDING_ENV_VAR not in seen
    assert "AWS_PROFILE" not in seen


# -- the guards fail when either defect comes back ----------------------------

_RESOLVER = re.compile(
    r"^def _assessment_runtime_binding\(\) -> Any:\n(?:.*\n)*?(?=^def |\Z)",
    re.MULTILINE,
)

_GATE = re.compile(
    r"^def _governed_identity_gate\(bound_account: str\) -> str \| None:\n(?:.*\n)*?(?=^def |\Z)",
    re.MULTILINE,
)


def _mutated(pattern: re.Pattern[str], replacement: str) -> str:
    """The entry point with one factory replaced. **In memory only.**"""
    assert len(pattern.findall(ASSESS_SOURCE)) == 1
    return pattern.sub(replacement, ASSESS_SOURCE, count=1)


DIRECT_REINTRODUCTION: Final = '''def _assessment_runtime_binding() -> Any:
    """The licensed bucket from governed Terraform state."""
    from aws_foundation_verify import tf_outputs

    return str(tf_outputs()["licensed_bucket_name"])


'''

ALIASED_REINTRODUCTION: Final = '''def _wrapped_outputs() -> dict:
    """A wrapper, so the forbidden name never appears at the call site."""
    from aws_foundation_verify import tf_outputs as _outputs

    return _outputs()


def _assessment_runtime_binding() -> Any:
    """The licensed bucket, one indirection away from the state read."""
    return str(_wrapped_outputs()["licensed_bucket_name"])


'''

FOUNDATION_PROFILE_FALLBACK: Final = '''def _assessment_runtime_binding() -> Any:
    """The binding, resolved by falling back to the foundation profile."""
    import os

    from aws_foundation_verify import EXPECTED_PROFILE

    os.environ["AWS_PROFILE"] = EXPECTED_PROFILE
    from kalpamani.data.qualify.sharadar.runtime_binding import load_assessment_runtime_binding

    return load_assessment_runtime_binding()


'''

RAW_ENVIRONMENT_BYPASS: Final = '''def _assessment_runtime_binding() -> Any:
    """The licensed bucket, straight out of an unvalidated environment variable."""
    import os

    return os.environ["KALPAMANI_LICENSED_BUCKET"]


'''

CAPTURE_REINTRODUCTION: Final = '''def _assessment_runtime_binding() -> Any:
    """The licensed bucket, by capturing it during the run."""
    from qualification_environment_binding_capture import _governed_outputs

    return str(_governed_outputs()["licensed_bucket_name"])


'''

MATERIALIZER_REINTRODUCTION: Final = '''def _assessment_runtime_binding() -> Any:
    """The binding, by materializing one during the run."""
    from qualification_assessment_binding_materialize import _expected_account

    return _expected_account()


'''

#: The corrected gate's signature, quoted once so the mutation literals below stay
#: inside the line ceiling while still parsing as replacements for it.
_GATE_SIGNATURE: Final = "def _governed_identity_gate(bound_account: str) -> str | None:"

ACCOUNT_FINDING_GATE: Final = (
    _GATE_SIGNATURE
    + '''
    """The gate that finds its own account binding, in the Terraform variables file."""
    from aws_foundation_verify import QualificationActor, qualification_identity_gate

    return qualification_identity_gate(QualificationActor.ASSESSMENT)


'''
)

TFVARS_ACCOUNT_REINTRODUCTION: Final = (
    _GATE_SIGNATURE
    + '''
    """The gate, with the account taken from the private Terraform input again."""
    from aws_foundation_verify import (
        QualificationActor,
        expected_account,
        qualification_identity_gate_for,
    )

    return qualification_identity_gate_for(
        QualificationActor.ASSESSMENT, bound_account=str(expected_account())
    )


'''
)


def test_the_mutation_helpers_actually_replace_the_targets() -> None:
    """A mutation that silently changed nothing would make every test below pass."""
    for pattern, replacement, gone in (
        (_RESOLVER, DIRECT_REINTRODUCTION, "load_assessment_runtime_binding"),
        (_GATE, ACCOUNT_FINDING_GATE, "qualification_identity_gate_for"),
    ):
        mutated = _mutated(pattern, replacement)
        assert mutated != ASSESS_SOURCE
        assert gone not in pattern.findall(mutated)[0]
        ast.parse(mutated)


def test_the_call_graph_catches_a_direct_reintroduction() -> None:
    findings = _terraform_findings(_mutated(_RESOLVER, DIRECT_REINTRODUCTION))
    assert "the Terraform state read is reachable" in findings
    assert "the pinned Terraform executable is reachable" in findings
    assert "the private assessment binding loader is not reachable" in findings


def test_the_call_graph_catches_a_reintroduction_behind_an_alias() -> None:
    """The exact case a source-string guard could never have seen."""
    mutated = _mutated(_RESOLVER, ALIASED_REINTRODUCTION)
    assert "tf_outputs()" not in _RESOLVER.findall(mutated)[0]
    findings = _terraform_findings(mutated)
    assert "the Terraform state read is reachable" in findings
    assert "the pinned Terraform executable is reachable" in findings


def test_the_call_graph_catches_a_fallback_to_the_foundation_profile() -> None:
    findings = _terraform_findings(_mutated(_RESOLVER, FOUNDATION_PROFILE_FALLBACK))
    assert "the shared foundation profile is reachable" in findings


def test_the_guards_catch_a_raw_bucket_environment_variable() -> None:
    """The file contract exists so nobody can name a licensed destination inline."""
    mutated = _mutated(_RESOLVER, RAW_ENVIRONMENT_BYPASS)
    assert _terraform_findings(mutated) == [
        "the private assessment binding loader is not reachable"
    ]
    assert "KALPAMANI_LICENSED_BUCKET" in _environment_names(mutated)
    assert _environment_names(mutated) != {"AWS_PROFILE"}


def test_the_call_graph_catches_a_capture_reached_from_the_run() -> None:
    """The operator tool is a way back to Terraform, so it is watched too."""
    mutated = _mutated(_RESOLVER, CAPTURE_REINTRODUCTION)
    assert "the environment-binding capture is reachable" in _operator_tool_findings(mutated)
    findings = _terraform_findings(mutated)
    assert "the Terraform state read is reachable" in findings


def test_the_call_graph_catches_the_assessment_materializer_reached_from_the_run() -> None:
    """Reaching the gate would reach the Terraform input through its own account read."""
    mutated = _mutated(_RESOLVER, MATERIALIZER_REINTRODUCTION)
    assert "the assessment-binding materialization gate is reachable" in _operator_tool_findings(
        mutated
    )
    findings = _terraform_findings(mutated)
    assert "the private Terraform account input is reachable" in findings
    assert "the local Terraform variables file is reachable" in findings


def test_the_call_graph_catches_the_account_finding_identity_gate() -> None:
    """The half of the defect a bucket-only correction would have left behind."""
    findings = _terraform_findings(_mutated(_GATE, ACCOUNT_FINDING_GATE))
    assert "the account-finding identity gate is reachable" in findings
    assert "the private Terraform account input is reachable" in findings
    assert "the local Terraform variables file is reachable" in findings
    assert "the actor-bound identity gate is not reachable" in findings


def test_the_call_graph_catches_the_terraform_input_read_directly() -> None:
    """Even with the corrected gate kept, reading the input is refused."""
    findings = _terraform_findings(_mutated(_GATE, TFVARS_ACCOUNT_REINTRODUCTION))
    assert "the private Terraform account input is reachable" in findings
    assert "the local Terraform variables file is reachable" in findings
    assert "the actor-bound identity gate is not reachable" not in findings


def test_the_repository_source_is_unchanged_by_any_mutation() -> None:
    """Every mutation above is a string. The file on disk is never rewritten."""
    assert ASSESS_PATH.read_text(encoding="utf-8") == ASSESS_SOURCE
    # Necessary and not sufficient -- the call graph above is the semantic guard --
    # and scanned on the raw file rather than the executable form on purpose: neither
    # name has a legitimate use in this module's prose either, so there is nothing to
    # exempt and no reason to accept the weaker scan.
    assert "tf_outputs" not in ASSESS_SOURCE
    assert "expected_account" not in ASSESS_SOURCE
