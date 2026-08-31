"""The two operator entry points: refused by default, and separately authorized.

**Neither entry point is ever invoked against a real dependency here**, and neither
could be: both refuse under ``pytest`` at stage 2, before anything is read or
resolved. The tests below drive their internal functions with injected fakes, which
is what the parameterised design exists to make possible.

The authorization objects are deliberately *not* exported, so the tests reach for
them through the module's private name -- and a test that has to do that is a reminder
that no ordinary caller can.
"""

from __future__ import annotations

import ast
import importlib.util
import re
from enum import StrEnum
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
ACQUIRE_PATH = SCRIPTS / "sharadar_empirical_qualification.py"
ASSESS_PATH = SCRIPTS / "sharadar_qualification_assessment.py"


def _module(name: str, path: Path) -> Any:
    """One entry point, imported by path. **Importing performs no activity.**

    Loaded the way every other operator-surface test in this suite loads one, and
    deliberately not with a plain ``import``: ``scripts/`` is on mypy's path but out
    of its ``files``, because the operational scripts predate strict typing and
    checking them is a separate decision. A direct import here would quietly reverse
    that decision for two files.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        pytest.fail("the entry point could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


acquire = _module("adr0018_acquisition_entry_point", ACQUIRE_PATH)
assess = _module("adr0018_assessment_entry_point", ASSESS_PATH)

ACQUIRE_SOURCE = ACQUIRE_PATH.read_text(encoding="utf-8")
ASSESS_SOURCE = ASSESS_PATH.read_text(encoding="utf-8")


def _executable(source: str) -> str:
    """The module with its docstrings removed, so prose cannot satisfy a check."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                body.pop(0)
    return ast.unparse(tree)


ACQUIRE_EXECUTABLE = _executable(ACQUIRE_SOURCE)
ASSESS_EXECUTABLE = _executable(ASSESS_SOURCE)

#: Keyed by a short name so a parametrised test id stays readable. Parametrising over
#: the sources themselves puts an entire module into the test id.
_EXECUTABLE = {"acquire": ACQUIRE_EXECUTABLE, "assess": ASSESS_EXECUTABLE}
_RAW = {"acquire": ACQUIRE_SOURCE, "assess": ASSESS_SOURCE}


# -- refused by default -------------------------------------------------------


def test_both_commands_refuse_without_their_authorization_flag(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert acquire.main([]) == acquire.EXIT_STATUS[acquire.EmpiricalOutcome.REFUSED_NOT_AUTHORIZED]
    assert assess.main([]) == assess.EXIT_STATUS[assess.AssessmentOutcome.REFUSED_NOT_AUTHORIZED]
    printed = capsys.readouterr().out
    assert "refused: not authorized" in printed


def test_the_two_authorization_flags_are_different() -> None:
    assert acquire.AUTHORIZATION_FLAG != assess.AUTHORIZATION_FLAG
    assert acquire.AUTHORIZATION_FLAG not in ASSESS_SOURCE
    assert assess.AUTHORIZATION_FLAG not in ACQUIRE_SOURCE


def test_neither_authorization_object_is_exported() -> None:
    # An exported capability is a public constructor by another name. The flag *name*
    # is a public constant and is not the capability, so the check is on the objects.
    for module, held in (
        (acquire, acquire._EMPIRICAL_AUTHORIZATION),
        (assess, assess._ASSESSMENT_AUTHORIZATION),
    ):
        exported = [getattr(module, name) for name in module.__all__]
        assert held not in exported
        assert type(held) not in exported


def test_neither_command_accepts_the_other_s_authorization() -> None:
    with pytest.raises(acquire.EmpiricalQualificationError) as raised:
        acquire.run_empirical_qualification(
            authorization=assess._ASSESSMENT_AUTHORIZATION,
            execution_id="synthetic-a",
            env={},
            modules={},
            load_inventory=lambda: None,
            profile_of=lambda: acquire.EXPECTED_PROFILE,
            identity_gate=lambda: None,
            resolve_licensed_bucket=lambda: "synthetic",
            secret_id_source=lambda: "x",
            secrets_client_factory=lambda: None,
            s3_client_factory=lambda: None,
            transport_factory=lambda: None,
            clock=None,
            monotonic=lambda: 0.0,
            sleeper=lambda _seconds: None,
        )
    assert raised.value.outcome is acquire.EmpiricalOutcome.REFUSED_NOT_AUTHORIZED


@pytest.mark.parametrize("candidate", [True, 1, "yes", object()])
def test_a_truthy_value_is_not_an_authorization(candidate: object) -> None:
    assert acquire._is_authorized(candidate) is False
    assert assess._is_authorized(candidate) is False


def test_the_authorization_is_a_singleton_that_cannot_be_copied_or_pickled() -> None:
    import copy
    import pickle

    for module in (acquire, assess):
        held = (
            module._EMPIRICAL_AUTHORIZATION
            if module is acquire
            else (module._ASSESSMENT_AUTHORIZATION)
        )
        with pytest.raises(TypeError):
            copy.copy(held)
        with pytest.raises(TypeError):
            copy.deepcopy(held)
        with pytest.raises(TypeError):
            pickle.dumps(held)
        with pytest.raises(TypeError):
            type(held)()


def test_an_object_new_instance_is_refused_because_it_is_not_this_object() -> None:
    forged = object.__new__(type(acquire._EMPIRICAL_AUTHORIZATION))
    assert acquire._is_authorized(forged) is False


# -- refused under automation -------------------------------------------------


def test_both_commands_refuse_under_pytest() -> None:
    assert acquire.running_under_automation({}, {"pytest": object()}) == "pytest"
    assert assess.running_under_automation({}, {"pytest": object()}) == "pytest"


@pytest.mark.parametrize(
    "variable", ["CI", "CONTINUOUS_INTEGRATION", "GITHUB_ACTIONS", "BUILD_NUMBER"]
)
def test_both_commands_refuse_in_continuous_integration(variable: str) -> None:
    assert acquire.running_under_automation({variable: "1"}, {}) == variable
    assert assess.running_under_automation({variable: "1"}, {}) == variable


def test_the_execution_context_is_checked_before_the_inventory_is_read() -> None:
    read = []
    with pytest.raises(acquire.EmpiricalQualificationError) as raised:
        acquire.run_empirical_qualification(
            authorization=acquire._EMPIRICAL_AUTHORIZATION,
            execution_id="synthetic-a",
            env={"CI": "1"},
            modules={},
            load_inventory=lambda: read.append("read"),
            profile_of=lambda: acquire.EXPECTED_PROFILE,
            identity_gate=lambda: None,
            resolve_licensed_bucket=lambda: "synthetic",
            secret_id_source=lambda: "x",
            secrets_client_factory=lambda: None,
            s3_client_factory=lambda: None,
            transport_factory=lambda: None,
            clock=None,
            monotonic=lambda: 0.0,
            sleeper=lambda _seconds: None,
        )
    assert raised.value.outcome is acquire.EmpiricalOutcome.REFUSED_EXECUTION_CONTEXT
    assert read == []


# -- no import-time side effects ----------------------------------------------


def test_importing_either_module_loads_no_aws_sdk() -> None:
    # Checked structurally rather than against ``sys.modules``: another test in the
    # session may legitimately have imported the SDK, so a runtime check would be
    # either flaky or -- as an earlier revision of this test was -- unconditionally
    # true and therefore worthless.
    for source in (ACQUIRE_EXECUTABLE, ASSESS_EXECUTABLE):
        tree = ast.parse(source)
        top_level_imports = [
            node for node in tree.body if isinstance(node, ast.Import | ast.ImportFrom)
        ]
        names = {alias.name for node in top_level_imports for alias in getattr(node, "names", [])}
        module_names = {getattr(node, "module", None) for node in top_level_imports}
        assert "boto3" not in names
        assert "boto3" not in module_names


def test_no_kalpamani_import_happens_at_module_level() -> None:
    for source in (ACQUIRE_EXECUTABLE, ASSESS_EXECUTABLE):
        tree = ast.parse(source)
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("kalpamani")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("kalpamani")


def test_no_environment_read_happens_at_module_level() -> None:
    # Inside a function body is exactly where these reads belong; what must not exist
    # is a read that happens on import.
    for source in (ACQUIRE_EXECUTABLE, ASSESS_EXECUTABLE):
        for node in ast.parse(source).body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                continue
            assert "os.environ" not in ast.unparse(node)


# -- the refused-option surface -----------------------------------------------


@pytest.mark.parametrize(
    "option",
    ["--subject", "--subjects", "--ticker", "--tickers", "--inventory", "--show-inventory"],
)
def test_the_acquisition_command_refuses_every_subject_carrying_option(option: str) -> None:
    assert option in acquire.REFUSED_OPTIONS


@pytest.mark.parametrize(
    "option",
    ["--dataset", "--window", "--from", "--to", "--page", "--limit", "--skip", "--retry"],
)
def test_the_acquisition_command_refuses_every_plan_widening_option(option: str) -> None:
    assert option in acquire.REFUSED_OPTIONS


@pytest.mark.parametrize(
    "option", ["--bulk", "--full-history", "--services-data", "--ingest", "--backfill", "--control"]
)
def test_the_acquisition_command_refuses_every_scope_widening_option(option: str) -> None:
    assert option in acquire.REFUSED_OPTIONS


@pytest.mark.parametrize(
    "option", ["--api-key", "--secret-id", "--secret", "--token", "--bucket", "--profile"]
)
def test_the_acquisition_command_refuses_every_credential_or_binding_option(option: str) -> None:
    assert option in acquire.REFUSED_OPTIONS


@pytest.mark.parametrize(
    "option",
    ["--list", "--list-locators", "--prefix", "--scan", "--print-report", "--show-findings"],
)
def test_the_assessment_command_refuses_every_search_or_disclosure_option(option: str) -> None:
    assert option in assess.REFUSED_OPTIONS


@pytest.mark.parametrize("option", ["--verdict", "--recommend", "--select-provider"])
def test_the_assessment_command_refuses_every_verdict_option(option: str) -> None:
    assert option in assess.REFUSED_OPTIONS


def test_a_refused_option_never_echoes_its_value(capsys: pytest.CaptureFixture[str]) -> None:
    acquire.main(["--subject=ZZ-SYNTH-01"])
    printed = capsys.readouterr().out
    assert "ZZ-SYNTH-01" not in printed
    assert "--subject" in printed


def test_the_acquisition_cli_accepts_exactly_two_arguments() -> None:
    actions = acquire.build_parser()._actions
    options = {option for action in actions for option in action.option_strings}
    assert options == {"-h", "--help", acquire.AUTHORIZATION_FLAG, "--execution-id"}


def test_the_assessment_cli_accepts_exactly_four_arguments() -> None:
    # Four, not three: the combined assessment names both executions. The old
    # single-execution spelling is refused by name rather than quietly accepted as
    # half a pair.
    actions = assess.build_parser()._actions
    options = {option for action in actions for option in action.option_strings}
    assert options == {
        "-h",
        "--help",
        assess.AUTHORIZATION_FLAG,
        "--run-a-execution-id",
        "--run-b-execution-id",
        "--assessment-id",
    }
    assert "--execution-id" in assess.REFUSED_OPTIONS


# -- allowlisted public output ------------------------------------------------


#: Words that would read as permission. Matched as **whole words**: a substring check
#: flags "the BOUNDED plan was refused" for containing "BOUND", and a test that fails
#: on a word the sentence does not actually contain is one people learn to weaken.
FORBIDDEN_IN_OUTPUT = frozenset(
    {"PROCEED", "HOLD", "REJECT", "QUALIFIED", "APPROVED", "READY", "BOUND", "AUTHORIZED"}
)


def test_no_outcome_sentence_reads_as_permission_or_a_verdict() -> None:
    # Refusals may legitimately say "not authorized", which is the opposite of
    # permission. What must never carry one of these words is a sentence a reader
    # could take as a go-ahead.
    for outcome in list(acquire.EmpiricalOutcome) + list(assess.AssessmentOutcome):
        if outcome.name.startswith("REFUSED"):
            continue
        words = set(re.findall(r"[A-Za-z]+", outcome.value.upper()))
        assert not words & FORBIDDEN_IN_OUTPUT


def test_every_refusal_sentence_says_it_refused() -> None:
    for outcome in list(acquire.EmpiricalOutcome) + list(assess.AssessmentOutcome):
        if outcome.name.startswith("REFUSED"):
            assert "refused:" in outcome.value


def test_no_outcome_sentence_carries_a_p_status_or_a_measurement() -> None:
    for outcome in list(acquire.EmpiricalOutcome) + list(assess.AssessmentOutcome):
        for word in ("P1", "P2", "P9", "TESTED", "PARTIALLY", "DEFERRED", "rows", "digest"):
            assert word not in outcome.value


def test_the_emit_helper_takes_a_vocabulary_member_and_not_a_string() -> None:
    for source, vocabulary in (
        (ACQUIRE_EXECUTABLE, acquire.EmpiricalOutcome),
        (ASSESS_EXECUTABLE, assess.AssessmentOutcome),
    ):
        assert "def _emit(outcome" in source
        assert vocabulary.__name__ in source


def test_the_exit_status_map_is_total_over_the_outcome_vocabulary() -> None:
    assert set(acquire.EXIT_STATUS) == set(acquire.EmpiricalOutcome)
    assert set(assess.EXIT_STATUS) == set(assess.AssessmentOutcome)


def test_only_a_complete_addressable_acquisition_exits_zero() -> None:
    zeros = [outcome for outcome, code in acquire.EXIT_STATUS.items() if code == 0]
    assert zeros == [acquire.EmpiricalOutcome.COMPLETED]


def test_a_partial_run_and_every_locator_problem_exit_non_zero() -> None:
    for outcome in (
        acquire.EmpiricalOutcome.COMPLETED_PARTIAL,
        acquire.EmpiricalOutcome.LOCATOR_NOT_PUBLISHED,
        acquire.EmpiricalOutcome.LOCATOR_STATE_UNKNOWN,
        acquire.EmpiricalOutcome.LOCATOR_COLLISION,
    ):
        assert acquire.EXIT_STATUS[outcome] != 0


def test_only_a_published_report_exits_zero_for_the_assessment() -> None:
    zeros = [outcome for outcome, code in assess.EXIT_STATUS.items() if code == 0]
    assert zeros == [assess.AssessmentOutcome.COMPLETED]


def test_every_exit_status_is_distinct() -> None:
    for mapping in (acquire.EXIT_STATUS, assess.EXIT_STATUS):
        assert len(set(mapping.values())) == len(mapping)


# -- the assessment command cannot reach a credential or a provider -----------


def test_the_assessment_module_names_no_credential_or_secret_boundary() -> None:
    for forbidden in (
        "secretsmanager",
        "get_secret_value",
        "sharadar_credential_from_secret",
        "is_usable_secret_identifier",
        "KALPAMANI_SHARADAR_SECRET_ID",
        "SharadarCredential",
        "UrllibTransport",
        "transport_factory",
    ):
        assert forbidden not in ASSESS_EXECUTABLE


def test_the_assessment_run_function_takes_no_credential_or_transport_parameter() -> None:
    import inspect

    signature = inspect.signature(assess.run_qualification_assessment)
    for forbidden in ("credential", "transport", "secret_id_source", "secrets_client_factory"):
        assert forbidden not in signature.parameters


def test_the_assessment_module_constructs_exactly_one_kind_of_client() -> None:
    assert ASSESS_EXECUTABLE.count("boto3.client(") == 1
    # ``ast.unparse`` renders string literals with single quotes.
    assert "boto3.client('s3'" in ASSESS_EXECUTABLE


def test_the_acquisition_module_reads_only_the_fixed_secret_identifier_name() -> None:
    assert ACQUIRE_EXECUTABLE.count("KALPAMANI_SHARADAR_SECRET_ID") == 1


# -- neither command writes locally, lists, or names CONTROL ------------------


@pytest.mark.parametrize("name", ["acquire", "assess"])
def test_neither_command_writes_a_local_file(name: str) -> None:
    for forbidden in ("write_text", "write_bytes", "mkdir", "tempfile", "open("):
        assert forbidden not in _EXECUTABLE[name]


@pytest.mark.parametrize("name", ["acquire", "assess"])
def test_neither_command_can_list_delete_or_copy(name: str) -> None:
    for forbidden in ("list_objects", "delete_object", "copy_object", "put_bucket"):
        assert forbidden not in _EXECUTABLE[name]


@pytest.mark.parametrize("name", ["acquire", "assess"])
def test_neither_command_names_the_control_bucket_output(name: str) -> None:
    source = _EXECUTABLE[name]
    assert "control_bucket" not in source
    assert "licensed_bucket_name" in source


@pytest.mark.parametrize("name", ["acquire", "assess"])
def test_neither_command_contains_a_security_symbol(name: str) -> None:
    # The acquisition takes its subjects from the owner-only inventory and the
    # assessment never sees one at all, so **no string literal anywhere in either
    # module may be shaped like a subject**. Checked against the accepted subject
    # grammar rather than against a list of names nobody can enumerate.
    subject_shaped = re.compile(r"^[A-Z][A-Z0-9.\-]{0,15}$")
    module = acquire if name == "acquire" else assess
    # A status token is vocabulary, not a symbol. The permitted set is derived from
    # the module's own closed vocabularies rather than hand-listed, so a member added
    # later is admitted as vocabulary and a stray literal still is not.
    from kalpamani.data.qualify.sharadar.acquisition import AcquisitionStatus
    from kalpamani.data.qualify.sharadar.assessment import AssessmentStatus

    permitted = (
        {
            member.value
            for value in vars(module).values()
            if isinstance(value, type) and issubclass(value, StrEnum)
            for member in value
        }
        # The keys of each total status mapping are another module's closed
        # vocabulary, so they are derived here too rather than hand-listed.
        | {member.name for member in AcquisitionStatus}
        | {member.name for member in AssessmentStatus}
        | {"CI", "CONTINUOUS_INTEGRATION", "GITHUB_ACTIONS", "BUILD_NUMBER", "AWS_PROFILE"}
    )
    for node in ast.walk(ast.parse(_RAW[name])):
        if isinstance(node, ast.Constant) and type(node.value) is str:
            if subject_shaped.match(node.value) and node.value not in permitted:
                raise AssertionError(f"a subject-shaped literal exists: {node.value!r}")
    assert "ZZ-SYNTH" not in _RAW[name]


@pytest.mark.parametrize("name", ["acquire", "assess"])
def test_neither_command_imports_the_public_test_key_harness(name: str) -> None:
    assert "sharadar_private_qualification" not in _EXECUTABLE[name]


@pytest.mark.parametrize("name", ["acquire", "assess"])
def test_neither_command_imports_the_earlier_authenticated_entry_point(name: str) -> None:
    source = _EXECUTABLE[name]
    assert "sharadar_authenticated_qualification" not in source
    assert "sharadar_binding_preflight" not in source


def test_both_commands_pin_the_governed_profile_and_never_accept_one() -> None:
    for module in (acquire, assess):
        assert module.EXPECTED_PROFILE == "kalpamani-foundation"
        assert "--profile" in module.REFUSED_OPTIONS


def test_neither_command_reimplements_the_identity_gate() -> None:
    for source in (ACQUIRE_EXECUTABLE, ASSESS_EXECUTABLE):
        assert "get-caller-identity" not in source
        assert "get_caller_identity" not in source
        # A bare "sts" substring appears inside "requests" and "exists"; what must be
        # absent is an STS call of this module's own.
        assert not re.search(r"[\"']sts[\"']", source)
        assert "allowed_account_ids" not in source
        assert "terraform" not in source.lower()
        assert "from aws_foundation_verify import identity_gate" in source
