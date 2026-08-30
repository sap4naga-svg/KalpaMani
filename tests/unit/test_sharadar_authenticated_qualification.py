"""The dormant ADR-0017 authenticated acquisition-qualification entry point.

The previous slice's finding was that ``pytest`` did not guard the binding
preflight's CLI spellings -- only the documentation audit did, and a text scan is
not a test of executable behaviour. **That does not recur here.** The exact
argument strings, the exact argument count, the exact authorization flag, the
refusal of similarly named aliases, the exact outcome vocabulary and the exact
process exit-code mapping are all asserted against the imported module.

Three kinds of check live here:

**Import safety.** A fresh interpreter imports the module with sockets replaced by
raising stubs and every file open recorded, and proves nothing was looked up,
constructed, opened or sent.

**Behavioural.** Every gate is driven with fakes that count what they were asked
for, so "the identifier was never resolved because identity refused" is a number
this file reads rather than a claim it repeats.

**Structural.** AST scans over the script proving the CLI is exactly three
arguments, that no parser exists, that the public harness is never imported and
that the binding preflight is never invoked.

Nothing here contacts Sharadar, AWS or any network. Every credential is a
self-labelled synthetic string and is never revealed, printed or sent.
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "scripts" / "sharadar_authenticated_qualification.py"
PUBLIC_HARNESS = PROJECT_ROOT / "scripts" / "sharadar_private_qualification.py"
BINDING_PREFLIGHT = PROJECT_ROOT / "scripts" / "sharadar_binding_preflight.py"

#: A synthetic subject. Not a listed security.
SUBJECT = "SYNTHETICA"
EXECUTION_ID = "synthetic-execution-01"

#: Disclosure canaries. Each must be absent from every outcome, message and
#: captured stream on every path.
SYNTHETIC_KEY = "synthetic-not-a-real-key"
SYNTHETIC_SECRET_ID = "synthetic-secret-identifier-name"  # noqa: S105 - a canary, not a value
SYNTHETIC_BUCKET = "synthetic-licensed-bucket-for-tests"
SYNTHETIC_ACCOUNT = "synthetic-account-canary"
SYNTHETIC_BACKEND_MESSAGE = "synthetic backend message naming a bucket and an ARN"


def _module() -> Any:
    """The entry point, imported by path. Importing performs no activity."""
    spec = importlib.util.spec_from_file_location("adr0017_entry_point", SCRIPT)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        pytest.fail("the entry point could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _module()


class FixedClock:
    """A clock answering one instant, so the window is reproducible."""

    def __init__(self, instant: datetime) -> None:
        self.instant = instant
        self.reads = 0

    def now(self) -> datetime:
        self.reads += 1
        return self.instant


class Recorder:
    """Every injected stage, counting what it was asked for.

    A stage that must not be reached is not merely absent: it is present, counted,
    and asserted at zero -- so the count is witnessed rather than inferred from
    which line happened to raise.
    """

    def __init__(
        self,
        *,
        profile: str = "kalpamani-foundation",
        identity_reason: str | None = None,
        bucket: str = SYNTHETIC_BUCKET,
        secret_id: str = SYNTHETIC_SECRET_ID,
        profile_raises: bool = False,
        identity_raises: bool = False,
        bucket_raises: bool = False,
        secret_id_raises: bool = False,
        secrets_client_raises: bool = False,
    ) -> None:
        self.profile = profile
        self.identity_reason = identity_reason
        self.bucket = bucket
        self.secret_id = secret_id
        self.profile_raises = profile_raises
        self.identity_raises = identity_raises
        self.bucket_raises = bucket_raises
        self.secret_id_raises = secret_id_raises
        self.secrets_client_raises = secrets_client_raises

        self.profile_reads = 0
        self.identity_calls = 0
        self.bucket_calls = 0
        self.secret_id_calls = 0
        self.secrets_clients = 0
        self.s3_clients = 0
        self.transports = 0

    def profile_of(self) -> str:
        self.profile_reads += 1
        if self.profile_raises:
            raise RuntimeError(SYNTHETIC_ACCOUNT)
        return self.profile

    def identity_gate(self) -> str | None:
        self.identity_calls += 1
        if self.identity_raises:
            raise RuntimeError(SYNTHETIC_ACCOUNT)
        return self.identity_reason

    def resolve_licensed_bucket(self) -> str:
        self.bucket_calls += 1
        if self.bucket_raises:
            raise RuntimeError(SYNTHETIC_BUCKET)
        return self.bucket

    def secret_id_source(self) -> str:
        self.secret_id_calls += 1
        if self.secret_id_raises:
            raise LookupError(SYNTHETIC_SECRET_ID)
        return self.secret_id

    def secrets_client_factory(self) -> Any:
        self.secrets_clients += 1
        if self.secrets_client_raises:
            raise ModuleNotFoundError("No module named 'boto3'")
        return object()

    def s3_client_factory(self) -> Any:
        self.s3_clients += 1
        return object()

    def transport_factory(self) -> Any:
        self.transports += 1
        return object()


def _run(
    recorder: Recorder,
    *,
    authorized: bool = True,
    subject: str | None = SUBJECT,
    execution_id: str | None = EXECUTION_ID,
    env: dict[str, str] | None = None,
    modules: dict[str, object] | None = None,
    clock: FixedClock | None = None,
) -> Any:
    """Drive the ordered gates with fakes, returning the outcome or the refusal."""
    authorization = MODULE._ACQUISITION_AUTHORIZATION if authorized else object()
    try:
        return MODULE.run_authenticated_qualification(
            authorization=authorization,
            subject=subject,
            execution_id=execution_id,
            env=env if env is not None else {},
            modules=modules if modules is not None else {},
            profile_of=recorder.profile_of,
            identity_gate=recorder.identity_gate,
            resolve_licensed_bucket=recorder.resolve_licensed_bucket,
            secret_id_source=recorder.secret_id_source,
            secrets_client_factory=recorder.secrets_client_factory,
            s3_client_factory=recorder.s3_client_factory,
            transport_factory=recorder.transport_factory,
            clock=clock or FixedClock(datetime(2026, 8, 30, 12, 0, tzinfo=UTC)),
        )
    except MODULE.AuthenticatedQualificationError as refusal:
        return refusal


# ---------------------------------------------------------------------------
# Import safety
# ---------------------------------------------------------------------------


def test_importing_the_entry_point_performs_no_activity() -> None:
    """A fresh interpreter, sockets stubbed, every open recorded."""
    probe = (
        "import builtins, socket, sys\n"
        "socket.socket = None\n"
        "socket.create_connection = None\n"
        "opened = []\n"
        "real_open = builtins.open\n"
        "builtins.open = lambda *a, **k: (opened.append(str(a[0])), real_open(*a, **k))[1]\n"
        "sys.path.insert(0, r'" + str(SCRIPT.parent) + "')\n"
        "import sharadar_authenticated_qualification as m\n"
        "builtins.open = real_open\n"
        "aws = [p for p in opened if '.aws' in p or 'credentials' in p]\n"
        "print('SDK', 'boto3' in sys.modules or 'botocore' in sys.modules)\n"
        "print('PKG', 'kalpamani' in sys.modules)\n"
        "print('AWSFILES', aws)\n"
        "print('FLAG', m.AUTHORIZATION_FLAG.startswith('--i-am-the-operator'))\n"
    )
    result = subprocess.run(  # noqa: S603 - fixed interpreter, fixed inline probe
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        cwd=str(PROJECT_ROOT),
    )
    assert result.returncode == 0, result.stderr
    assert "SDK False" in result.stdout
    assert "PKG False" in result.stdout
    assert "AWSFILES []" in result.stdout
    assert "FLAG True" in result.stdout


def test_importing_the_entry_point_reads_no_environment_variable() -> None:
    probe = (
        "import os, sys\n"
        "reads = []\n"
        "real = os.environ.get\n"
        "os.environ.get = lambda k, d=None: (reads.append(k), real(k, d))[1]\n"
        "sys.path.insert(0, r'" + str(SCRIPT.parent) + "')\n"
        "import sharadar_authenticated_qualification\n"
        "os.environ.get = real\n"
        "print('SECRETREADS', [k for k in reads if 'SECRET' in k or 'AWS' in k])\n"
    )
    result = subprocess.run(  # noqa: S603 - fixed interpreter, fixed inline probe
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        cwd=str(PROJECT_ROOT),
    )
    assert result.returncode == 0, result.stderr
    assert "SECRETREADS []" in result.stdout


# ---------------------------------------------------------------------------
# CLI surface -- executable, not a text scan
# ---------------------------------------------------------------------------


def _option_strings() -> list[str]:
    parser = MODULE.build_parser()
    return sorted(option for action in parser._actions for option in action.option_strings)


def test_the_cli_carries_exactly_the_three_approved_arguments() -> None:
    assert _option_strings() == sorted(
        [
            "-h",
            "--help",
            "--i-am-the-operator-authorizing-authenticated-qualification",
            "--subject",
            "--execution-id",
        ]
    )


def test_the_cli_has_exactly_three_arguments_beyond_help() -> None:
    assert len([opt for opt in _option_strings() if opt not in {"-h", "--help"}]) == 3


def test_the_authorization_flag_is_exactly_the_approved_spelling() -> None:
    assert MODULE.AUTHORIZATION_FLAG == (
        "--i-am-the-operator-authorizing-authenticated-qualification"
    )
    assert MODULE.AUTHORIZATION_FLAG in _option_strings()


@pytest.mark.parametrize(
    "alias",
    [
        "--run",
        "--live",
        "--execute",
        "--force",
        "--secret-id",
        "--api-key",
        "--dataset",
        "--table",
        "--bucket",
        "--endpoint",
        "--profile",
        "--aws-profile",
        "--window",
        "--page",
        "--limit",
        "--skip",
        "--retry",
        "--retries",
        "--full-history",
        "--full",
        "--bulk",
        "--archive",
        "--services-data",
        "--ingest",
        "--control",
        "--arn",
        "--token",
    ],
)
def test_every_forbidden_alias_is_absent_from_the_cli(alias: str) -> None:
    assert alias not in _option_strings()


@pytest.mark.parametrize("alias", ["--run", "--live", "--execute", "--force", "--secret-id"])
def test_a_forbidden_alias_is_refused_by_name_with_a_reason(
    alias: str, capsys: pytest.CaptureFixture[str]
) -> None:
    status = MODULE.main([alias, MODULE.AUTHORIZATION_FLAG])
    captured = capsys.readouterr().out
    assert status == MODULE.EXIT_STATUS[MODULE.AcquisitionOutcome.REFUSED_OPTION]
    assert MODULE.AcquisitionOutcome.REFUSED_OPTION.value in captured
    assert alias in captured


def test_a_forbidden_alias_with_a_value_never_echoes_the_value(
    capsys: pytest.CaptureFixture[str],
) -> None:
    MODULE.main([f"--secret-id={SYNTHETIC_SECRET_ID}", MODULE.AUTHORIZATION_FLAG])
    assert SYNTHETIC_SECRET_ID not in capsys.readouterr().out


def test_the_default_invocation_refuses_before_anything_else(
    capsys: pytest.CaptureFixture[str],
) -> None:
    status = MODULE.main([])
    captured = capsys.readouterr().out
    assert status == MODULE.EXIT_STATUS[MODULE.AcquisitionOutcome.REFUSED_NOT_AUTHORIZED]
    assert MODULE.AcquisitionOutcome.REFUSED_NOT_AUTHORIZED.value in captured


def test_a_subject_without_the_flag_still_refuses(capsys: pytest.CaptureFixture[str]) -> None:
    status = MODULE.main(["--subject", SUBJECT, "--execution-id", EXECUTION_ID])
    capsys.readouterr()
    assert status == MODULE.EXIT_STATUS[MODULE.AcquisitionOutcome.REFUSED_NOT_AUTHORIZED]


def test_every_outcome_has_an_exact_exit_status() -> None:
    """Total, with no default: a member added later has no status and fails here."""
    assert set(MODULE.EXIT_STATUS) == set(MODULE.AcquisitionOutcome)


def test_only_completion_exits_zero() -> None:
    zeros = [outcome for outcome, status in MODULE.EXIT_STATUS.items() if status == 0]
    assert zeros == [MODULE.AcquisitionOutcome.COMPLETED]


def test_every_refusal_exits_non_zero() -> None:
    refusals = {
        outcome: status
        for outcome, status in MODULE.EXIT_STATUS.items()
        if outcome is not MODULE.AcquisitionOutcome.COMPLETED
    }
    assert all(status > 0 for status in refusals.values())


def test_the_outcome_vocabulary_is_the_accepted_set() -> None:
    assert {outcome.name for outcome in MODULE.AcquisitionOutcome} == {
        "REFUSED_NOT_AUTHORIZED",
        "REFUSED_OPTION",
        "REFUSED_EXECUTION_CONTEXT",
        "REFUSED_SUBJECT",
        "REFUSED_PROFILE",
        "REFUSED_IDENTITY",
        "REFUSED_LICENSED_BUCKET",
        "REFUSED_SECRET_IDENTIFIER",
        "REFUSED_SECRETS_ACCESS",
        "REFUSED_CREDENTIAL",
        "REFUSED_DEPENDENCY",
        "REFUSED_PLAN",
        "REFUSED_PROVIDER_REQUEST",
        "REFUSED_RESPONSE_SIZE",
        "REFUSED_PUBLICATION",
        "REFUSED_UNCLASSIFIED",
        "COMPLETED",
    }


def test_no_outcome_sentence_implies_permission_or_a_verdict() -> None:
    for outcome in MODULE.AcquisitionOutcome:
        # "not authorized" is a refusal, and the only legitimate appearance of the
        # word: removing it first is what makes the remaining scan a check for a
        # *grant* rather than a check that the word is unused.
        upper = outcome.value.upper().replace("NOT AUTHORIZED", "")
        for forbidden in ("READY", "APPROVED", "AUTHORIZED", "PROCEED", "QUALIFIED", "SELECTED"):
            assert forbidden not in upper


# ---------------------------------------------------------------------------
# Gate ordering -- each proven by a witnessed zero on the next stage
# ---------------------------------------------------------------------------


def test_the_missing_operator_flag_refuses_before_every_dependency() -> None:
    recorder = Recorder()
    result = _run(recorder, authorized=False)
    assert result.outcome is MODULE.AcquisitionOutcome.REFUSED_NOT_AUTHORIZED
    assert (recorder.profile_reads, recorder.identity_calls, recorder.secret_id_calls) == (0, 0, 0)


def test_a_pytest_context_refuses_before_every_dependency() -> None:
    recorder = Recorder()
    result = _run(recorder, modules={"pytest": object()})
    assert result.outcome is MODULE.AcquisitionOutcome.REFUSED_EXECUTION_CONTEXT
    assert (recorder.profile_reads, recorder.identity_calls, recorder.secret_id_calls) == (0, 0, 0)


@pytest.mark.parametrize("marker", ["CI", "CONTINUOUS_INTEGRATION", "GITHUB_ACTIONS"])
def test_a_ci_context_refuses_before_every_dependency(marker: str) -> None:
    recorder = Recorder()
    result = _run(recorder, env={marker: "1"})
    assert result.outcome is MODULE.AcquisitionOutcome.REFUSED_EXECUTION_CONTEXT
    assert recorder.profile_reads == 0


def test_the_real_module_refuses_under_this_test_process() -> None:
    """The ambient guard, not the injected one: ``pytest`` really is imported."""
    assert MODULE.running_under_automation({}, sys.modules) == "pytest"


@pytest.mark.parametrize("bad", ["", "not a ticker", "toolongsubjectvaluehere" * 4, "AA PL"])
def test_an_invalid_subject_refuses_before_profile_and_aws(bad: str) -> None:
    recorder = Recorder()
    result = _run(recorder, subject=bad)
    assert result.outcome is MODULE.AcquisitionOutcome.REFUSED_SUBJECT
    assert (recorder.profile_reads, recorder.identity_calls) == (0, 0)


@pytest.mark.parametrize("bad", ["", "Has Spaces", "UPPERCASE", "x" * 64])
def test_an_invalid_execution_id_refuses_before_profile_and_aws(bad: str) -> None:
    recorder = Recorder()
    result = _run(recorder, execution_id=bad)
    assert result.outcome is MODULE.AcquisitionOutcome.REFUSED_SUBJECT
    assert (recorder.profile_reads, recorder.identity_calls) == (0, 0)


def test_a_missing_subject_refuses_before_profile_and_aws() -> None:
    recorder = Recorder()
    result = _run(recorder, subject=None)
    assert result.outcome is MODULE.AcquisitionOutcome.REFUSED_SUBJECT
    assert recorder.profile_reads == 0


def test_a_wrong_profile_prevents_the_identity_gate() -> None:
    recorder = Recorder(profile="some-other-profile")
    result = _run(recorder)
    assert result.outcome is MODULE.AcquisitionOutcome.REFUSED_PROFILE
    assert (recorder.identity_calls, recorder.bucket_calls, recorder.secret_id_calls) == (0, 0, 0)


def test_an_identity_refusal_prevents_bucket_resolution() -> None:
    recorder = Recorder(identity_reason="synthetic refusal reason")
    result = _run(recorder)
    assert result.outcome is MODULE.AcquisitionOutcome.REFUSED_IDENTITY
    assert (recorder.bucket_calls, recorder.secret_id_calls, recorder.secrets_clients) == (0, 0, 0)


def test_a_bucket_refusal_prevents_identifier_resolution() -> None:
    recorder = Recorder(bucket_raises=True)
    result = _run(recorder)
    assert result.outcome is MODULE.AcquisitionOutcome.REFUSED_LICENSED_BUCKET
    assert (recorder.secret_id_calls, recorder.secrets_clients) == (0, 0)


def test_an_identifier_refusal_prevents_secrets_client_construction() -> None:
    recorder = Recorder(secret_id_raises=True)
    result = _run(recorder)
    assert result.outcome is MODULE.AcquisitionOutcome.REFUSED_SECRET_IDENTIFIER
    assert (recorder.secrets_clients, recorder.s3_clients, recorder.transports) == (0, 0, 0)


def test_an_ungrammatical_identifier_refuses_without_a_client() -> None:
    recorder = Recorder(secret_id="not a usable identifier at all!!")  # noqa: S106
    result = _run(recorder)
    assert result.outcome is MODULE.AcquisitionOutcome.REFUSED_SECRET_IDENTIFIER
    assert recorder.secrets_clients == 0


def test_a_missing_sdk_is_a_dependency_refusal_and_never_a_credential_claim() -> None:
    """ADR-0016's correction, held to in the new surface."""
    recorder = Recorder(secrets_client_raises=True)
    result = _run(recorder)
    assert result.outcome is MODULE.AcquisitionOutcome.REFUSED_DEPENDENCY
    assert (recorder.s3_clients, recorder.transports) == (0, 0)


def test_the_secret_identifier_is_resolved_at_most_once() -> None:
    recorder = Recorder(secrets_client_raises=True)
    _run(recorder)
    assert recorder.secret_id_calls == 1


def test_the_licensed_bucket_is_resolved_at_most_once() -> None:
    recorder = Recorder(secrets_client_raises=True)
    _run(recorder)
    assert recorder.bucket_calls == 1


def test_the_identity_gate_is_invoked_at_most_once() -> None:
    recorder = Recorder(secrets_client_raises=True)
    _run(recorder)
    assert recorder.identity_calls == 1


def test_an_invalid_credential_prevents_provider_and_s3_construction() -> None:
    """The synthetic secrets client returns something the contract refuses."""
    recorder = Recorder()
    result = _run(recorder)
    assert result.outcome is MODULE.AcquisitionOutcome.REFUSED_CREDENTIAL
    assert (recorder.s3_clients, recorder.transports) == (0, 0)


# ---------------------------------------------------------------------------
# The locked plan and its window
# ---------------------------------------------------------------------------


def _plan(instant: datetime | None = None) -> Any:
    return MODULE.build_locked_plan(
        subject=SUBJECT,
        execution_id=EXECUTION_ID,
        instant=instant or datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
    )


def test_the_locked_dataset_is_exactly_stocks() -> None:
    from kalpamani.data.ingest.sharadar.datasets import SharadarDataset

    assert [plan.dataset for plan in _plan().datasets] == [SharadarDataset.STOCKS]


def test_the_plan_names_exactly_one_subject() -> None:
    assert len(_plan().subjects) == 1


def test_the_plan_declares_one_dataset_and_one_page() -> None:
    datasets = _plan().datasets
    assert len(datasets) == 1
    assert datasets[0].max_pages == 1


def test_the_page_offset_is_zero() -> None:
    pages = _plan().datasets[0].pages()
    assert [page.skip for page in pages] == [0]


def test_the_page_limit_is_positive_and_at_most_ten() -> None:
    limit = _plan().datasets[0].page_limit
    assert 1 <= limit <= MODULE.PAGE_LIMIT_CEILING


def test_the_locked_page_limit_constant_is_the_smallest_positive_value() -> None:
    assert MODULE.PAGE_LIMIT == 1
    assert MODULE.PAGE_SKIP == 0


def test_the_plan_derives_exactly_one_request() -> None:
    plan = _plan()
    assert len(plan.subjects) * sum(d.max_pages for d in plan.datasets) == 1


def test_the_acquisition_mode_is_qualification() -> None:
    from kalpamani.data.contracts.vocabulary import AcquisitionMode
    from kalpamani.data.ingest.sharadar.qualification import QUALIFICATION_ACQUISITION_MODE

    assert QUALIFICATION_ACQUISITION_MODE is AcquisitionMode.QUALIFICATION


def test_no_acquisition_mode_is_selectable_from_the_cli() -> None:
    assert not any("mode" in option for option in _option_strings())


def test_the_retry_policy_is_exactly_one_attempt_with_no_backoff() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "RetryPolicy(max_attempts=1, backoff_seconds=())" in source


def test_the_window_is_seven_calendar_days_ending_the_previous_utc_date() -> None:
    window = MODULE.qualification_window(datetime(2026, 8, 30, 12, 0, tzinfo=UTC))
    assert window.end == date(2026, 8, 29)
    assert window.start == date(2026, 8, 23)
    assert (window.end - window.start).days == 6


def test_the_window_is_a_pure_function_of_the_injected_clock() -> None:
    instant = datetime(2026, 1, 1, 3, 30, tzinfo=UTC)
    first = MODULE.qualification_window(instant)
    second = MODULE.qualification_window(instant)
    assert (first.start, first.end) == (second.start, second.end)
    assert first.end == date(2025, 12, 31)


def test_the_window_crosses_a_year_boundary_correctly() -> None:
    window = MODULE.qualification_window(datetime(2026, 1, 3, 0, 1, tzinfo=UTC))
    assert (window.start, window.end) == (date(2025, 12, 27), date(2026, 1, 2))


def test_the_window_end_is_never_the_invocation_date() -> None:
    instant = datetime(2026, 8, 30, 23, 59, tzinfo=UTC)
    assert MODULE.qualification_window(instant).end != instant.date()


def test_no_alternate_dataset_or_widened_window_exists_in_the_source() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("fundamentals", "SF1", "SF2", "SF3", "years=", "lastupdated"):
        assert forbidden not in source


def test_the_source_contains_no_pagination_walk() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "advanced()" not in source


# ---------------------------------------------------------------------------
# Structural: the script composes, imports no harness, invokes no preflight
# ---------------------------------------------------------------------------


def _executable_source(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def test_the_script_never_imports_the_public_test_token_harness() -> None:
    source = _executable_source(SCRIPT)
    assert "sharadar_private_qualification" not in source
    assert "PUBLIC_TEST_API_KEY" not in source


def test_the_script_never_invokes_the_binding_preflight() -> None:
    source = _executable_source(SCRIPT)
    assert "sharadar_binding_preflight" not in source
    assert "run_binding_preflight" not in source


def test_the_script_introduces_no_parser() -> None:
    source = _executable_source(SCRIPT)
    for forbidden in ("csv", "DictReader", "json.loads", "splitlines", ".decode("):
        assert forbidden not in source


def test_the_script_writes_no_file_and_names_no_runtime_directory() -> None:
    source = _executable_source(SCRIPT)
    for forbidden in (".runtime/", "write_text", "write_bytes", "mkdir", "tempfile", "open("):
        assert forbidden not in source


def test_the_script_never_names_the_control_classification() -> None:
    source = _executable_source(SCRIPT)
    assert "control_bucket_name" not in source
    assert "ObjectClassification.CONTROL" not in source


def test_the_script_calls_the_accepted_composition_root_and_no_other() -> None:
    source = _executable_source(SCRIPT)
    assert "execute_qualification_acquisition" in source
    assert source.count("execute_qualification_acquisition") == 2


def test_the_script_constructs_no_store_client_or_runtime_of_its_own() -> None:
    source = _executable_source(SCRIPT)
    for forbidden in ("S3ResearchObjectStore(", "QualificationRuntime(", "SharadarClient("):
        assert forbidden not in source


def test_the_public_harness_and_binding_preflight_are_untouched_by_this_slice() -> None:
    """Both still exist and still declare their own, different, entry points."""
    for path, marker in (
        (PUBLIC_HARNESS, "PUBLIC_TEST_API_KEY"),
        (BINDING_PREFLIGHT, "BINDING_AUTHORIZATION_FLAG"),
    ):
        assert marker in path.read_text(encoding="utf-8")


def test_the_script_exports_no_authorization_capability() -> None:
    assert "_ACQUISITION_AUTHORIZATION" not in MODULE.__all__
    assert "_AcquisitionAuthorization" not in MODULE.__all__


def test_the_authorization_capability_cannot_be_copied_or_constructed_again() -> None:
    import copy

    with pytest.raises(TypeError, match="singleton"):
        type(MODULE._ACQUISITION_AUTHORIZATION)()
    with pytest.raises(TypeError, match="copied"):
        copy.copy(MODULE._ACQUISITION_AUTHORIZATION)
    with pytest.raises(TypeError, match="copied"):
        copy.deepcopy(MODULE._ACQUISITION_AUTHORIZATION)


def test_a_look_alike_object_is_not_the_authorization() -> None:
    impostor = object.__new__(type(MODULE._ACQUISITION_AUTHORIZATION))
    recorder = Recorder()
    result = _run(recorder, authorized=False)
    assert result.outcome is MODULE.AcquisitionOutcome.REFUSED_NOT_AUTHORIZED
    assert not MODULE._is_authorized(impostor)


# ---------------------------------------------------------------------------
# Disclosure
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "recorder_kwargs",
    [
        {"profile_raises": True},
        {"identity_raises": True},
        {"bucket_raises": True},
        {"secret_id_raises": True},
        {"secrets_client_raises": True},
        {"secret_id": SYNTHETIC_SECRET_ID},
    ],
)
def test_no_canary_survives_into_any_refusal(recorder_kwargs: dict[str, Any]) -> None:
    recorder = Recorder(**recorder_kwargs)
    result = _run(recorder)
    text = f"{result!r} {result} {getattr(result, 'outcome', '')}"
    for canary in (
        SYNTHETIC_KEY,
        SYNTHETIC_SECRET_ID,
        SYNTHETIC_BUCKET,
        SYNTHETIC_ACCOUNT,
        SYNTHETIC_BACKEND_MESSAGE,
    ):
        assert canary not in text


@pytest.mark.parametrize(
    "recorder_kwargs",
    [
        {"profile_raises": True},
        {"identity_raises": True},
        {"identity_reason": SYNTHETIC_ACCOUNT},
        {"bucket_raises": True},
        {"secret_id_raises": True},
        {"secrets_client_raises": True},
        {"secret_id": SYNTHETIC_SECRET_ID},
    ],
)
def test_no_canary_reaches_stdout_on_any_refusal_path(
    recorder_kwargs: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    """Every stage, not one. A negative control added ``print(exc)`` to a single
    ``except`` and a one-path check did not see it -- the stream has to be watched
    while the run happens, on every branch that can refuse."""
    recorder = Recorder(**recorder_kwargs)
    result = _run(recorder)
    MODULE._emit(result.outcome)
    captured = capsys.readouterr()
    for canary in (
        SYNTHETIC_KEY,
        SYNTHETIC_SECRET_ID,
        SYNTHETIC_BUCKET,
        SYNTHETIC_ACCOUNT,
        SYNTHETIC_BACKEND_MESSAGE,
    ):
        assert canary not in captured.out
        assert canary not in captured.err


def test_the_governed_profile_value_is_never_printed(capsys: pytest.CaptureFixture[str]) -> None:
    MODULE.main([])
    captured = capsys.readouterr().out
    assert MODULE.EXPECTED_PROFILE not in captured


def test_no_outcome_sentence_contains_a_private_shaped_value() -> None:
    for outcome in MODULE.AcquisitionOutcome:
        for forbidden in ("arn:", "http", "s3://", "amazonaws", "kalpamani-"):
            assert forbidden not in outcome.value.lower()


def test_a_raw_exception_never_becomes_the_public_outcome() -> None:
    recorder = Recorder(identity_raises=True)
    result = _run(recorder)
    assert isinstance(result, MODULE.AuthenticatedQualificationError)
    assert str(result) == MODULE.AcquisitionOutcome.REFUSED_IDENTITY.value


# ---------------------------------------------------------------------------
# Disclosure past the credential gate
# ---------------------------------------------------------------------------
#
# The canary block above drives gates 1-9 and stops there. It cannot go further:
# the real credential contract refuses the fake secrets client, so every one of
# those runs refuses at gate 9. That left gates 10-12 -- and in particular the
# `except Exception` wrapping the acquisition, the one handler whose own comment
# says a provider error can carry a URL that *is* a credential and a store error
# can quote the bucket -- asserted by source inspection alone. A `print(exc)`
# there would have leaked an API key and no test would have failed.
#
# These reach that handler, still entirely on fakes: the credential and the
# acquisition are patched on the modules the run imports from at call time, so
# no AWS client, transport, store or provider request is constructed anywhere.


class _SyntheticCredential:
    """A credential-shaped stand-in. ``reveal`` exists and is never called here."""

    def reveal(self) -> str:  # pragma: no cover - asserted absent, never invoked
        return SYNTHETIC_KEY


def _past_the_credential(monkeypatch: pytest.MonkeyPatch, *, acquisition: Any) -> None:
    """Let gate 9 succeed and route gates 11-12 to ``acquisition``.

    Both names are imported *inside* ``run_authenticated_qualification``, so
    patching the owning modules is what the run will actually see. Nothing real
    is constructed: ``Pacer`` and ``RetryPolicy`` are pure value objects, and the
    injected S3 client and transport are the recorder's inert sentinels.
    """
    from kalpamani.data.ingest.sharadar import composition, secrets

    monkeypatch.setattr(
        secrets,
        "sharadar_credential_from_secret",
        lambda **_kwargs: _SyntheticCredential(),
    )
    monkeypatch.setattr(composition, "execute_qualification_acquisition", acquisition)


#: Failures the acquisition can raise that carry something disclosive. The first
#: is the dangerous one: the vendor takes the key in the query string, so a
#: request URL in an exception message *is* a credential.
ACQUISITION_FAILURES = [
    pytest.param(
        RuntimeError(f"GET https://example.invalid/datasets?api_key={SYNTHETIC_KEY} failed"),
        id="provider-url-bearing-the-key",
    ),
    pytest.param(RuntimeError(SYNTHETIC_BUCKET), id="store-error-quoting-the-bucket"),
    pytest.param(RuntimeError(SYNTHETIC_BACKEND_MESSAGE), id="backend-message"),
    pytest.param(RuntimeError(SYNTHETIC_ACCOUNT), id="account-canary"),
    pytest.param(RuntimeError(SYNTHETIC_SECRET_ID), id="secret-identifier"),
]


@pytest.mark.parametrize("failure", ACQUISITION_FAILURES)
def test_no_canary_reaches_stdout_when_the_acquisition_raises(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: Exception,
) -> None:
    """The acquisition wrapper refuses without echoing what the exception carried."""

    def raising(**_kwargs: Any) -> Any:
        raise failure

    _past_the_credential(monkeypatch, acquisition=raising)
    result = _run(Recorder())
    assert result.outcome is MODULE.AcquisitionOutcome.REFUSED_UNCLASSIFIED

    MODULE._emit(result.outcome)
    captured = capsys.readouterr()
    for canary in (
        SYNTHETIC_KEY,
        SYNTHETIC_SECRET_ID,
        SYNTHETIC_BUCKET,
        SYNTHETIC_ACCOUNT,
        SYNTHETIC_BACKEND_MESSAGE,
    ):
        assert canary not in captured.out
        assert canary not in captured.err
        assert canary not in f"{result!r} {result} {result.outcome}"


@pytest.mark.parametrize("failure", ACQUISITION_FAILURES)
def test_the_acquisition_refusal_suppresses_the_exception_chain(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    """``from None`` on the wrapper, so a traceback cannot carry the cause either."""

    def raising(**_kwargs: Any) -> Any:
        raise failure

    _past_the_credential(monkeypatch, acquisition=raising)
    result = _run(Recorder())
    assert result.__cause__ is None
    assert result.__suppress_context__ is True


def test_the_acquisition_is_called_exactly_once_and_never_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One call, counted -- the behavioural half of the source-level count."""
    calls: list[dict[str, Any]] = []

    def recording(**kwargs: Any) -> Any:
        calls.append(kwargs)
        raise RuntimeError(SYNTHETIC_BACKEND_MESSAGE)

    _past_the_credential(monkeypatch, acquisition=recording)
    _run(Recorder())
    assert len(calls) == 1


class _CompletedOutcome:
    """The runtime's own success member, by name -- nothing else is read."""

    name = "COMPLETED"


class _CompletedResult:
    """A run result shaped as the classifier reads it. Carries no payload."""

    outcome = _CompletedOutcome()
    failure = None


def test_a_successful_acquisition_is_called_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One call on the path that *returns*, which is where a retry loop would show.

    The refusal-path count above cannot see a loop: its fake raises, so the body
    leaves on the first iteration whatever the loop says. A returning fake is the
    only shape in which ``for _ in range(2)`` would call twice.
    """
    calls: list[dict[str, Any]] = []

    def returning(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return _CompletedResult()

    _past_the_credential(monkeypatch, acquisition=returning)
    outcome = _run(Recorder())
    assert outcome is MODULE.AcquisitionOutcome.COMPLETED
    assert len(calls) == 1


def test_a_completed_acquisition_discloses_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Success is an allowlisted sentence too, and it names nothing."""

    def returning(**_kwargs: Any) -> Any:
        return _CompletedResult()

    _past_the_credential(monkeypatch, acquisition=returning)
    outcome = _run(Recorder())
    MODULE._emit(outcome)
    captured = capsys.readouterr()
    for canary in (
        SYNTHETIC_KEY,
        SYNTHETIC_SECRET_ID,
        SYNTHETIC_BUCKET,
        SYNTHETIC_ACCOUNT,
        SYNTHETIC_BACKEND_MESSAGE,
        SUBJECT,
    ):
        assert canary not in captured.out
        assert canary not in captured.err


def test_the_acquisition_receives_the_locked_plan_and_a_one_attempt_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What the wrapper hands the composition root is the locked plan, once."""
    seen: dict[str, Any] = {}

    def capturing(**kwargs: Any) -> Any:
        seen.update(kwargs)
        raise RuntimeError(SYNTHETIC_BACKEND_MESSAGE)

    _past_the_credential(monkeypatch, acquisition=capturing)
    _run(Recorder())
    assert seen["retry_policy"].max_attempts == 1
    assert seen["retry_policy"].backoff_seconds == ()
    assert seen["licensed_bucket"] == SYNTHETIC_BUCKET
    plan = seen["plan"]
    assert len(plan.datasets) == 1
    assert plan.datasets[0].dataset.value == MODULE.LOCKED_DATASET_NAME
    assert plan.datasets[0].max_pages == MODULE.MAX_PAGES


def test_a_dependency_failure_after_the_credential_is_a_dependency_refusal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Gate 10 refuses as a dependency, and names nothing, after a credential exists."""

    def unreachable(**_kwargs: Any) -> Any:  # pragma: no cover - never reached
        pytest.fail("the acquisition ran after a dependency failure")

    _past_the_credential(monkeypatch, acquisition=unreachable)

    class Failing(Recorder):
        def s3_client_factory(self) -> Any:
            self.s3_clients += 1
            raise RuntimeError(SYNTHETIC_BUCKET)

    recorder = Failing()
    result = _run(recorder)
    assert result.outcome is MODULE.AcquisitionOutcome.REFUSED_DEPENDENCY
    assert recorder.s3_clients == 1

    MODULE._emit(result.outcome)
    captured = capsys.readouterr()
    assert SYNTHETIC_BUCKET not in captured.out
    assert SYNTHETIC_BUCKET not in captured.err
    assert SYNTHETIC_BUCKET not in f"{result!r} {result}"


#: A subject the plan grammar refuses, shaped so that echoing it would be visible.
#: Gate 3's own comment says the plan refusal can quote a subject, which makes this
#: the one early gate with something of the operator's to disclose.
SYNTHETIC_SUBJECT_CANARY = "synthetic-subject-canary-!!!-not-a-ticker"


@pytest.mark.parametrize(
    ("label", "kwargs", "expected"),
    [
        ("not-authorized", {"authorized": False}, "REFUSED_NOT_AUTHORIZED"),
        ("under-pytest", {"modules": {"pytest": object()}}, "REFUSED_EXECUTION_CONTEXT"),
        ("malformed-subject", {"subject": SYNTHETIC_SUBJECT_CANARY}, "REFUSED_SUBJECT"),
    ],
)
def test_the_early_gates_refuse_without_echoing_their_input(
    capsys: pytest.CaptureFixture[str],
    label: str,
    kwargs: dict[str, Any],
    expected: str,
) -> None:
    """Gates 1-3 refuse before any private value is read -- and still echo nothing.

    They hold no credential, bucket or identifier, so there is less to leak here
    than later. The subject is the exception: it is the operator's input, the plan
    refusal can quote it, and only the closed outcome may survive.
    """
    recorder = Recorder()
    result = _run(recorder, **kwargs)
    assert result.outcome.name == expected

    MODULE._emit(result.outcome)
    captured = capsys.readouterr()
    for canary in (SYNTHETIC_SUBJECT_CANARY, SUBJECT, EXECUTION_ID):
        assert canary not in captured.out
        assert canary not in captured.err
        assert canary not in f"{result!r} {result} {result.outcome}"

    # Refusing early means refusing before anything private was even read.
    assert recorder.secret_id_calls == 0
    assert recorder.secrets_clients == 0


def test_every_refusal_outcome_the_gates_can_reach_is_canary_covered() -> None:
    """The gap this section closes, asserted so it cannot silently reopen.

    Six outcomes were reachable by the original canary block; ``REFUSED_SUBJECT``,
    ``REFUSED_NOT_AUTHORIZED``, ``REFUSED_EXECUTION_CONTEXT`` and
    ``REFUSED_UNCLASSIFIED`` were not reachable at all -- and the last of those is
    the handler a provider URL bearing the key would pass through. If a future
    change adds a gate outcome, this fails until a canary case reaches it.
    """
    covered = {
        "REFUSED_NOT_AUTHORIZED",
        "REFUSED_EXECUTION_CONTEXT",
        "REFUSED_SUBJECT",
        "REFUSED_PROFILE",
        "REFUSED_IDENTITY",
        "REFUSED_LICENSED_BUCKET",
        "REFUSED_SECRET_IDENTIFIER",
        "REFUSED_DEPENDENCY",
        "REFUSED_CREDENTIAL",
        "REFUSED_UNCLASSIFIED",
    }
    raised_by_gates = {
        node.exc.args[0].attr
        for node in ast.walk(ast.parse(SCRIPT.read_text(encoding="utf-8")))
        if isinstance(node, ast.Raise)
        and isinstance(node.exc, ast.Call)
        and isinstance(node.exc.func, ast.Name)
        and node.exc.func.id == "AuthenticatedQualificationError"
        and isinstance(node.exc.args[0], ast.Attribute)
    }
    assert raised_by_gates <= covered, f"uncovered gate outcomes: {raised_by_gates - covered}"


# ---------------------------------------------------------------------------
# Governance semantics
# ---------------------------------------------------------------------------


def test_the_module_claims_no_gate_closure_or_provider_selection() -> None:
    source = SCRIPT.read_text(encoding="utf-8").upper()
    for forbidden in ("G1 CLOSED", "G2 CLOSED", "PROVIDER SELECTED", "PROVIDER IS SELECTED"):
        assert forbidden not in source


def test_the_module_claims_no_empirical_qualification_or_data_quality() -> None:
    source = SCRIPT.read_text(encoding="utf-8").upper()
    for forbidden in ("P1-P9 COMPLETE", "SCHEMA VALIDATED", "DATA QUALITY CONFIRMED"):
        assert forbidden not in source


def _folded(text: str) -> str:
    """``text`` with emphasis dropped, whitespace collapsed and case folded.

    Docstrings wrap, and a rewrap is what an editor or a formatter does to a long
    sentence. Folding first means these assertions are about what the module
    *says*, not about where its lines happen to break.
    """
    return " ".join(text.replace("**", "").split()).lower()


def _function_docstring(tree: ast.Module, name: str) -> str:
    """The docstring of the module-level function ``name``, or ``""``.

    Scoped on purpose. A whole-file search is satisfied by any copy of a phrase
    anywhere in the script, including inside a different function that a reader
    of ``main`` would never see.
    """
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_docstring(node) or ""
    return ""


def test_the_module_records_one_refused_attempt_and_one_completed_attempt() -> None:
    """The module's own status must match what the one attempt actually did.

    This replaces a bare ``"never been run" in doc`` assertion. That check was
    written while the surface was unexecuted, and it survived the surface being
    invoked: any sentence containing those three words satisfied it, including a
    true one about a different subject. What follows asserts the facts instead.

    The two easiest to conflate are asserted apart from each other. *Attempt one
    refused* and *attempt two completed* are both true, and a summary that reports
    only one of them misdescribes the surface. Both are required here, together
    with the boundary that a completed command status is not a qualification
    verdict, so none of the three can drift out unnoticed.
    """
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    module_doc = _folded(ast.get_docstring(tree) or "")
    main_doc = _folded(_function_docstring(tree, "main"))

    assert module_doc, "the module docstring is the status surface asserted against here"
    assert main_doc, "main's own docstring must say what main has done"

    # Attempt one: refused -- where, with which outcome, and with which code.
    for fact in (
        "it has been attempted exactly twice: the first refused and the second completed",
        "refused at stage 5",
        "the existing aws identity gate",
        "the closed outcome was ``refused_identity``",
        "the exit code was ``6``",
        "authorized attempts two one refused, one completed",
        "attempt one -- refused: refused_identity, exit code 6, stage 5",
        "attempt one -- provider requests: zero",
        "attempt one -- qualification-runtime executions against real services: zero",
        "attempt one -- s3 qualification operations: zero",
    ):
        assert fact in module_doc, f"missing from the module docstring: {fact}"
    assert "this function has been run exactly twice" in main_doc
    assert "refused at the aws identity gate" in main_doc

    # Attempt two: completed, and exactly what that does and does not establish.
    for fact in (
        "the second attempt completed",
        "the qualification runtime was reached",
        "one provider request was reported",
        "attempt two's s3 qualification operations are not established",
        "not established is never read as zero",
        "attempt two -- qualification runtime reached: yes · runtime executions: one",
        "attempt two -- provider requests: one, reported",
        "cumulative -- qualification-runtime executions: one · provider requests: one",
    ):
        assert fact in module_doc, f"missing from the module docstring: {fact}"

    # A command status is not a verdict, and the module has to say so.
    assert "``completed`` is a command status, not a verdict" in module_doc
    assert "provider authentication stays unknown" in module_doc
    assert "not a selection of a provider" in module_doc

    # A completed authorization is not a standing one.
    assert "authorization for another request" in module_doc
    assert "a third attempt · aws identity diagnosis · sso refresh: not authorized" in module_doc
    assert "a third bounded authenticated acquisition qualification is a separate" in module_doc

    # The claims the one attempt makes false, absent from both docstrings.
    for stale in (
        "it has never been run.",
        "this function has never been run",
        "the entry point has never been run",
        "the entry point was never invoked",
        "authorized attempts zero",
        "the bounded acquisition has never completed",
        "no provider request has ever been made from here",
    ):
        assert stale not in module_doc, f"stale claim in the module docstring: {stale}"
        assert stale not in main_doc, f"stale claim in main's docstring: {stale}"


def test_the_module_keeps_q7_unresolved() -> None:
    doc = ast.get_docstring(ast.parse(SCRIPT.read_text(encoding="utf-8"))) or ""
    assert "PUBLICLY_UNRESOLVED" in doc
