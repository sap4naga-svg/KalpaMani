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
import subprocess
import sys
from enum import StrEnum
from pathlib import Path
from typing import Any

# The SDK ships no type information. It is imported for two purposes only: to replace
# ``boto3.client`` with a recorder, and to read a ``Config`` OBJECT back. **No client
# is ever constructed**, so no credential or endpoint is resolved and no socket opens.
import boto3  # type: ignore[import-untyped]
import pytest
from botocore.config import Config  # type: ignore[import-untyped]

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


def test_a_partial_run_and_every_occupied_or_locator_problem_exit_non_zero() -> None:
    for outcome in (
        acquire.EmpiricalOutcome.COMPLETED_PARTIAL,
        acquire.EmpiricalOutcome.BRONZE_NAME_OCCUPIED,
        acquire.EmpiricalOutcome.LOCATOR_NOT_PUBLISHED,
        acquire.EmpiricalOutcome.LOCATOR_STATE_UNKNOWN,
        acquire.EmpiricalOutcome.LOCATOR_NAME_OCCUPIED,
    ):
        assert acquire.EXIT_STATUS[outcome] != 0


def test_the_two_occupied_name_sentences_claim_nothing_about_the_stored_content() -> None:
    """A ``412`` says a name was taken. The public sentence may say no more.

    ``LOCATOR_COLLISION``'s sentence said *held by other content*, which was a
    metadata comparison; ADR-0019 removed the authority to make it, so the word had
    to go with it rather than survive as an unbacked claim.
    """
    for outcome in (
        acquire.EmpiricalOutcome.BRONZE_NAME_OCCUPIED,
        acquire.EmpiricalOutcome.LOCATOR_NAME_OCCUPIED,
    ):
        sentence = outcome.value
        assert "occupied" in sentence
        for forbidden in (
            "other content",
            "different",
            "identical",
            "already present",
            "adopted",
            "resumed",
            "collision",
        ):
            assert forbidden not in sentence.lower()


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


def test_each_command_pins_its_own_governed_actor_profile_and_never_accepts_one() -> None:
    """One profile each, and the shared foundation profile reaches neither.

    ADR-0021 replaced the single ``kalpamani-foundation`` pin with two actor-specific
    profiles, so this asserts the pair rather than one constant. The old spelling is
    refused by name: a revert would otherwise route both actors back through one
    credential source while every other guard here stayed green.
    """
    assert acquire.EXPECTED_PROFILE == "kalpamani-qualification-acquisition"
    assert assess.EXPECTED_PROFILE == "kalpamani-qualification-assessment"
    assert acquire.EXPECTED_PROFILE != assess.EXPECTED_PROFILE
    for module in (acquire, assess):
        assert module.EXPECTED_PROFILE != "kalpamani-foundation"
        assert "--profile" in module.REFUSED_OPTIONS


def test_neither_command_reimplements_the_identity_gate() -> None:
    for source in (ACQUIRE_EXECUTABLE, ASSESS_EXECUTABLE):
        assert "get-caller-identity" not in source
        assert "get_caller_identity" not in source
        # A bare "sts" substring appears inside "requests" and "exists"; what must be
        # absent is an STS call of this module's own.
        assert not re.search(r"[\"']sts[\"']", source)
        assert "allowed_account_ids" not in source
        # NECESSARY, AND NOT SUFFICIENT. This finds a Terraform reference spelled in
        # the entry point's own text and nothing else -- and the ADR-0023 defect was
        # never spelled here: the acquisition path said
        # ``from aws_foundation_verify import tf_outputs``, and the subprocess lived
        # one module away, so this assertion was green throughout. The real guard is
        # the name-level call graph and the runtime sentinel in
        # ``test_sharadar_acquisition_terraform_isolation.py``.
        assert "terraform" not in source.lower()
        assert "import identity_gate" not in source

    # The ADR-0021 gate, still imported from the one governed verifier rather than
    # rebuilt in either command. **Each actor's gate is pinned exactly**, because the
    # two are no longer the same function: ADR-0025 gave the assessment one that takes
    # its account binding as an argument, so the acquisition path keeps the gate that
    # reads the local Terraform variables file and the assessment path gets the one
    # that cannot. A substring assertion would let either drift onto the other's.
    acquire_imports = {line.strip() for line in ACQUIRE_EXECUTABLE.splitlines()}
    assess_imports = {line.strip() for line in ASSESS_EXECUTABLE.splitlines()}
    assert (
        "from aws_foundation_verify import QualificationActor, qualification_identity_gate"
    ) in acquire_imports
    assert "qualification_identity_gate_for" not in ACQUIRE_EXECUTABLE
    assert (
        "from aws_foundation_verify import QualificationActor, qualification_identity_gate_for"
    ) in assess_imports
    # Necessary and not sufficient, and the semantic guard is the call graph in
    # ``test_sharadar_assessment_terraform_isolation.py``: the assessment path must
    # reach neither the state read nor the local Terraform account binding.
    for forbidden in ("tf_outputs", "expected_account", "terraform.tfvars"):
        assert forbidden not in ASSESS_EXECUTABLE, forbidden


def test_each_command_proves_its_own_actor_and_not_the_other() -> None:
    """Acquisition names only ACQUISITION, assessment names only ASSESSMENT.

    A copy-paste that left both commands proving one actor would pass every other
    guard in this file: both would import the gate, both would pin a distinct
    profile, and both would refuse ``--profile``. Only this asserts the pairing.
    """
    assert "QualificationActor.ACQUISITION" in ACQUIRE_EXECUTABLE
    assert "QualificationActor.ASSESSMENT" not in ACQUIRE_EXECUTABLE
    assert "QualificationActor.ASSESSMENT" in ASSESS_EXECUTABLE
    assert "QualificationActor.ACQUISITION" not in ASSESS_EXECUTABLE


def test_the_acquisition_s3_client_factory_uses_the_compiled_sdk_configuration() -> None:
    """The one qualification S3 client factory takes its ``Config`` from the plan.

    Checked on the executable source, not on a constructed client: constructing one
    would resolve credentials and an endpoint, and this suite reaches no AWS. What
    matters is that the factory passes ``s3_client_config_kwargs()`` straight into
    ``botocore``'s ``Config`` -- the same module the operation ceiling is derived in,
    so the two cannot drift apart -- and names no retry setting of its own.
    """
    source = ACQUIRE_EXECUTABLE
    assert "from botocore.config import Config" in source
    assert "from kalpamani.data.qualify.sharadar.plan import s3_client_config_kwargs" in source
    assert "config=Config(**s3_client_config_kwargs())" in source
    # No literal retry configuration anywhere in either command: the values live in
    # one compiled place, and a second spelling is how two of them drift apart.
    for name in ("acquire", "assess"):
        executable = _EXECUTABLE[name]
        assert '"retries"' not in executable
        assert "'retries'" not in executable
        assert '"max_attempts"' not in executable
        assert "'max_attempts'" not in executable
        assert "adaptive" not in executable
        assert "legacy" not in executable


def test_the_acquisition_command_states_the_corrected_botocore_semantics() -> None:
    # The prose the correction replaced said botocore's ``max_attempts`` of one was
    # one total attempt. An operator reading the factory now reads the distinction
    # that actually holds, in the file that builds the client.
    assert "``total_max_attempts``, not ``max_attempts``" in ACQUIRE_SOURCE
    assert "counts the retries that follow the first request" in ACQUIRE_SOURCE
    assert "max_attempts" not in ACQUIRE_EXECUTABLE


# -- both qualification S3 clients take exactly one SDK attempt ---------------


def _recorded_client_construction(module: Any, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Drive one command's S3 factory with ``boto3.client`` replaced by a recorder.

    **No client is constructed and nothing reaches AWS.** The recorder returns an
    inert sentinel, so no credential is resolved, no endpoint is looked up and no
    socket is opened -- and `monkeypatch` restores the SDK afterwards. This is the
    only way to assert what the factory *actually passes*: a source check can be
    satisfied by a line that never runs, and a real client cannot be built here.
    """
    recorded: dict[str, Any] = {}

    def _recorder(service_name: str, **kwargs: Any) -> object:
        assert not recorded, "the factory constructed more than one client"
        recorded["service_name"] = service_name
        recorded.update(kwargs)
        return object()

    monkeypatch.setattr(boto3, "client", _recorder)
    module._s3_client()
    return recorded


@pytest.mark.parametrize("name", ["acquire", "assess"])
def test_both_qualification_s3_factories_construct_an_explicit_botocore_config(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded = _recorded_client_construction(
        {"acquire": acquire, "assess": assess}[name], monkeypatch
    )
    assert recorded["service_name"] == "s3"
    assert recorded["region_name"] == "us-east-1"
    # An explicit Config object, not a dictionary and not the SDK's default.
    assert type(recorded["config"]) is Config


@pytest.mark.parametrize("name", ["acquire", "assess"])
def test_both_qualification_s3_clients_take_one_total_attempt_and_no_retry(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One total SDK attempt per invocation, on both commands.

    Read off the ``Config`` the factory really passed, so this is what the SDK would
    be given rather than what a docstring says it would be given.
    """
    config = _recorded_client_construction(
        {"acquire": acquire, "assess": assess}[name], monkeypatch
    )["config"]
    assert config.retries == {"total_max_attempts": 1, "mode": "standard"}
    assert config.retries["total_max_attempts"] == 1
    assert "max_attempts" not in config.retries
    assert config.retries["mode"] == "standard"
    assert config.retries["mode"] != "adaptive"
    # Both socket timeouts are finite, so one attempt cannot hang indefinitely.
    for value in (config.connect_timeout, config.read_timeout):
        assert type(value) is float
        assert 0 < value < float("inf")


def test_the_two_commands_are_given_the_same_compiled_client_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # One shared pure source, so no retry literal is written twice and the two
    # cannot drift apart. The assessment command previously passed no ``Config`` at
    # all and therefore inherited the SDK's default retry behaviour.
    from kalpamani.data.qualify.sharadar.plan import s3_client_config_kwargs

    acquire_config = _recorded_client_construction(acquire, monkeypatch)["config"]
    assess_config = _recorded_client_construction(assess, monkeypatch)["config"]
    expected = s3_client_config_kwargs()
    for config in (acquire_config, assess_config):
        assert config.retries == expected["retries"]
        assert config.connect_timeout == expected["connect_timeout"]
        assert config.read_timeout == expected["read_timeout"]
    assert acquire_config.retries == assess_config.retries
    assert "s3_client_config_kwargs" in ASSESS_EXECUTABLE
    assert "config=Config(**s3_client_config_kwargs())" in ASSESS_EXECUTABLE


@pytest.mark.parametrize("name", ["acquire", "assess"])
def test_ambient_retry_settings_cannot_override_either_client_configuration(
    name: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """A hostile environment and a hostile shared profile change nothing.

    ``AWS_MAX_ATTEMPTS`` and ``AWS_RETRY_MODE``, and the same two settings in a
    shared-profile file reached through ``AWS_CONFIG_FILE``, are what would otherwise
    decide a client's retry behaviour. Both are set to values this path forbids, and
    the ``Config`` the factory passes is unchanged -- because the values come from a
    pure function that reads no environment, and an explicitly configured ``Config``
    is what botocore's own resolution chain prefers over either source.
    """
    profile = tmp_path / "config"
    profile.write_text("[default]\nmax_attempts = 10\nretry_mode = adaptive\n", encoding="utf-8")
    monkeypatch.setenv("AWS_MAX_ATTEMPTS", "10")
    monkeypatch.setenv("AWS_RETRY_MODE", "adaptive")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(profile))

    config = _recorded_client_construction(
        {"acquire": acquire, "assess": assess}[name], monkeypatch
    )["config"]
    assert config.retries == {"total_max_attempts": 1, "mode": "standard"}


def test_constructing_the_client_configuration_reaches_nothing() -> None:
    """Building the ``Config`` opens no file, no socket and no AWS session.

    In a **fresh interpreter**, because by the time this test runs some earlier test
    has imported the SDK and this process would say nothing. The SDK is imported
    first and the guards are installed after, so the probe measures the construction
    rather than the import.
    """
    probe = (
        "import sys, builtins, socket\n"
        "from botocore.config import Config\n"
        "from kalpamani.data.qualify.sharadar.plan import s3_client_config_kwargs\n"
        "import boto3\n"
        "def _forbidden(*a, **k):\n"
        "    raise AssertionError('network')\n"
        "socket.socket.connect = _forbidden\n"
        "socket.create_connection = _forbidden\n"
        "socket.getaddrinfo = _forbidden\n"
        "opened = []\n"
        "real_open = builtins.open\n"
        "builtins.open = lambda *a, **k: (opened.append(str(a[0])), real_open(*a, **k))[1]\n"
        "config = Config(**s3_client_config_kwargs())\n"
        "builtins.open = real_open\n"
        "print('RETRIES', config.retries['total_max_attempts'], config.retries['mode'])\n"
        "print('OPENED', opened)\n"
        "print('SESSION', boto3.DEFAULT_SESSION is None)\n"
    )
    completed = subprocess.run(  # noqa: S603 - fixed interpreter, fixed inline probe
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    lines = completed.stdout.splitlines()
    assert lines[0] == "RETRIES 1 standard", completed.stdout
    assert lines[1] == "OPENED []", completed.stdout
    assert lines[2] == "SESSION True", completed.stdout


def test_importing_the_assessment_command_constructs_no_client() -> None:
    """An ordinary import performs nothing observable, and pulls in no SDK.

    The shared configuration is imported **inside** the factory, so importing the
    command still reaches neither ``botocore`` nor the data platform. A fresh
    interpreter again, for the same reason.
    """
    probe = (
        "import sys, builtins, socket\n"
        "def _forbidden(*a, **k):\n"
        "    raise AssertionError('network')\n"
        "socket.socket.connect = _forbidden\n"
        "socket.create_connection = _forbidden\n"
        "socket.getaddrinfo = _forbidden\n"
        "opened = []\n"
        "real_open = builtins.open\n"
        "builtins.open = lambda *a, **k: (opened.append(str(a[0])), real_open(*a, **k))[1]\n"
        "sys.path.insert(0, r'" + str(SCRIPTS) + "')\n"
        "import sharadar_qualification_assessment as m\n"
        "builtins.open = real_open\n"
        "aws = [p for p in opened if '.aws' in p or 'credentials' in p]\n"
        "print('SDK', 'boto3' in sys.modules or 'botocore' in sys.modules)\n"
        "print('PKG', 'kalpamani' in sys.modules)\n"
        "print('AWSFILES', aws)\n"
        "print('FLAG', m.AUTHORIZATION_FLAG.startswith('--i-am-the-operator'))\n"
    )
    completed = subprocess.run(  # noqa: S603 - fixed interpreter, fixed inline probe
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    assert completed.stdout.split() == [
        "SDK",
        "False",
        "PKG",
        "False",
        "AWSFILES",
        "[]",
        "FLAG",
        "True",
    ], completed.stdout


def test_the_assessment_client_factory_stays_dormant_on_the_refusal_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The factory is injected, not called at import and not called before the command
    # is authorized. Proven by making any client construction fail loudly and then
    # driving the unauthorized path, which must still refuse cleanly.
    def _explode(*args: Any, **kwargs: Any) -> object:
        raise AssertionError("a client was constructed on the refusal path")

    monkeypatch.setattr(boto3, "client", _explode)
    assert assess.main([]) == assess.EXIT_STATUS[assess.AssessmentOutcome.REFUSED_NOT_AUTHORIZED]
    assert "refused: not authorized" in capsys.readouterr().out
    # And it reaches the composition only as the injected default, in one place: the
    # module never calls its own factory, so nothing but the authorized path can.
    assert ASSESS_EXECUTABLE.count("s3_client_factory=_s3_client") == 1
    assert _calls_to(ASSESS_SOURCE, "_s3_client") == 0
    assert _calls_to(ACQUIRE_SOURCE, "_s3_client") == 0


def _calls_to(source: str, name: str) -> int:
    """How many times ``name`` is *called* -- a definition or a reference is not one."""
    return sum(
        1
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
    )


@pytest.mark.parametrize("name", ["acquire", "assess"])
def test_neither_command_holds_a_retry_loop(name: str) -> None:
    """No application-level retry compensates for the SDK taking none.

    A structural check rather than a text one: both commands *name* ``--retry`` and
    ``--retries``, because they refuse those options, so a word search would prove
    the opposite of what it looked like. What must be absent is the shape -- there is
    no ``while`` anywhere in either module, and nothing that reaches AWS sits inside
    a loop.
    """
    tree = ast.parse(_RAW[name])
    assert not [node for node in ast.walk(tree) if isinstance(node, ast.While)]
    looped: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.For | ast.AsyncFor):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name):
                looped.append(inner.func.id)
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute):
                looped.append(inner.func.attr)
    for forbidden in (
        "_s3_client",
        "client",
        "put_object",
        "get_object",
        "head_object",
        "publish_report",
        "run_combined_assessment",
        "execute_qualification_acquisition",
    ):
        assert forbidden not in looped


def test_the_assessment_command_publishes_through_one_unrepeated_call() -> None:
    # One composition call, outside every loop. A second call, or one inside a loop,
    # would be an application-level retry of an operation the accounting counts once.
    tree = ast.parse(ASSESS_SOURCE)
    assert _calls_to(ASSESS_SOURCE, "run_combined_assessment") == 1
    inside_a_loop = [
        inner
        for node in ast.walk(tree)
        if isinstance(node, ast.For | ast.AsyncFor | ast.While)
        for inner in ast.walk(node)
        if isinstance(inner, ast.Call)
        and isinstance(inner.func, ast.Name)
        and inner.func.id == "run_combined_assessment"
    ]
    assert inside_a_loop == []


def test_the_shared_configuration_adds_no_module_to_the_assessment_graph() -> None:
    """Sharing the configuration widens nothing the assessment could already reach.

    In a **fresh interpreter**: import the accepted assessment composition, snapshot
    ``sys.modules``, then import the shared configuration function. The set must not
    grow -- the plan module is already reachable through the locator, so the factory's
    function-local import is a lookup rather than a new dependency.

    It also records what the accepted composition already pulls in, so the claim stays
    honest: ``kalpamani.data.ingest.sharadar.transport`` was already in this graph
    before this correction, through the accepted composition, and is unchanged by it.
    What the composition must not *directly* import is asserted separately, in the
    package-boundary suite.
    """
    probe = (
        "import sys\n"
        "import kalpamani.data.qualify.sharadar.assessment\n"
        "before = set(sys.modules)\n"
        "from kalpamani.data.qualify.sharadar.plan import s3_client_config_kwargs\n"
        "print('NEW', sorted(set(sys.modules) - before))\n"
        "print('PLAN', 'kalpamani.data.qualify.sharadar.plan' in before)\n"
        "print('SDK', 'boto3' in sys.modules or 'botocore' in sys.modules)\n"
        "print('SECRETS', [m for m in sys.modules if 'secrets' in m])\n"
    )
    completed = subprocess.run(  # noqa: S603 - fixed interpreter, fixed inline probe
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    assert completed.stdout.splitlines() == [
        "NEW []",
        "PLAN True",
        "SDK False",
        "SECRETS []",
    ], completed.stdout
