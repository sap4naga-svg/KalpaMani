"""The private Sharadar qualification harness, guarded by test.

Everything here runs against **hand-authored synthetic fixtures**. No Sharadar row
enters this file, no example from the vendor's API documentation is reused, and
**nothing here opens a socket** -- the harness's own automation guard refuses to grant
network authority while ``pytest`` is running, which is itself one of the tests below.

Four properties are worth stating, because they are what the tests are really about and
each is a *disclosure* control rather than a correctness one:

1. **Network is unreachable without a deliberate, gated invocation.** Not "there is a
   check"; the fetching functions cannot be called at all without a token only the
   authorization path can mint.
2. **Nothing that leaves the process carries a conclusion.** stdout is an allowlist, the
   exit code is derived from an object that has no verdict field, and error text is
   assembled from stage/table/code rather than redacted after the fact.
3. **Optimism is refused structurally.** P2 cannot pass, P7 and P8 cannot pass, P9 cannot
   reach ``PUBLIC_PIT``, P1 cannot reach ``TESTED``, P4 is documentation-resolved and can
   never shed ``CLASSIFICATION_STATIC``, and P5 cannot reach ``TESTED`` because its spinoff
   limb cannot be exercised from this surface at all.
5. **Pessimism is refused too.** The vendor published its adjustment methodology on
   2026-07-29, so a limb that *can* now be reconciled must be, and a fixture that reaches a
   favourable outcome exists precisely so the conservative assertions cannot pass against a
   function that always says "no".
4. **Licensed evidence is never lost and never misfiled.** Raw payloads go to the
   licensed bucket and are deleted locally only once they are there; a failed upload
   keeps them.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import urllib.error
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from fixtures import sharadar_qualification as fx

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HARNESS_PATH = PROJECT_ROOT / "scripts" / "sharadar_private_qualification.py"
_HARNESS_MODULE = "kalpamani_sharadar_private_qualification"


def _load_harness() -> Any:
    """Import the harness by path.

    That this import is *safe* is part of what is under test: the module must reach no
    network, read no credential and contact no AWS service at import time.
    """
    if _HARNESS_MODULE in sys.modules:
        return sys.modules[_HARNESS_MODULE]
    spec = importlib.util.spec_from_file_location(_HARNESS_MODULE, HARNESS_PATH)
    assert spec is not None and spec.loader is not None, "could not load the qualification harness"
    module = importlib.util.module_from_spec(spec)
    sys.modules[_HARNESS_MODULE] = module
    spec.loader.exec_module(module)
    return module


H = _load_harness()


def _grant() -> Any:
    """A live-run authorization, minted the way the harness itself mints one.

    Tests need one to reach the fetch and storage functions. It is produced through the
    real gate with the real flag, and with an injected identity gate that passes -- so
    the test exercises the authorization path rather than sidestepping it.
    """
    return H.authorize_live_run(
        argv=("--private-live-run",),
        env={"AWS_PROFILE": H.EXPECTED_PROFILE},
        modules={},
        identity_gate=lambda: None,
    )


def _samples(payloads: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for table, text in payloads.items():
        raw = text.encode("utf-8")
        out[table] = H.parse_csv_payload(table, raw, H.content_address(raw))
    return out


BUCKETS = H.ResearchBuckets(licensed="licensed-bucket-fixture", control="control-bucket-fixture")


# ---------------------------------------------------------------------------
# Network is off by default
# ---------------------------------------------------------------------------


def test_network_is_refused_without_the_private_live_run_flag() -> None:
    with pytest.raises(H.SafeHarnessError) as excinfo:
        H.authorize_live_run(argv=(), env={"AWS_PROFILE": H.EXPECTED_PROFILE}, modules={})
    assert "PRIVATE_LIVE_RUN_FLAG_ABSENT" in str(excinfo.value)


def test_the_flag_alone_is_not_enough_the_aws_profile_must_be_pinned() -> None:
    with pytest.raises(H.SafeHarnessError) as excinfo:
        H.authorize_live_run(
            argv=("--private-live-run",),
            env={"AWS_PROFILE": "default"},
            modules={},
            identity_gate=lambda: None,
        )
    assert "AWS_PROFILE_NOT_PINNED" in str(excinfo.value)


def test_an_absent_aws_profile_is_refused_rather_than_defaulted() -> None:
    with pytest.raises(H.SafeHarnessError) as excinfo:
        H.authorize_live_run(
            argv=("--private-live-run",), env={}, modules={}, identity_gate=lambda: None
        )
    assert "AWS_PROFILE_NOT_PINNED" in str(excinfo.value)


def test_a_failed_aws_identity_check_refuses_the_run() -> None:
    with pytest.raises(H.SafeHarnessError) as excinfo:
        H.authorize_live_run(
            argv=("--private-live-run",),
            env={"AWS_PROFILE": H.EXPECTED_PROFILE},
            modules={},
            identity_gate=lambda: "the authenticated account does not match the binding",
        )
    assert "AWS_IDENTITY_CHECK_FAILED" in str(excinfo.value)


def test_the_identity_failure_reason_is_not_echoed_back() -> None:
    """A gate reason may describe the account. The refusal code must not carry it."""
    gate_reason = "account-shaped-detail-that-must-not-escape"
    with pytest.raises(H.SafeHarnessError) as excinfo:
        H.authorize_live_run(
            argv=("--private-live-run",),
            env={"AWS_PROFILE": H.EXPECTED_PROFILE},
            modules={},
            identity_gate=lambda: gate_reason,
        )
    assert gate_reason not in str(excinfo.value)


def test_no_network_under_pytest_even_with_the_flag_and_a_passing_gate() -> None:
    """The real running environment: pytest is in sys.modules, so the run is refused."""
    with pytest.raises(H.SafeHarnessError) as excinfo:
        H.authorize_live_run(
            argv=("--private-live-run",),
            env={"AWS_PROFILE": H.EXPECTED_PROFILE},
            identity_gate=lambda: None,
        )
    assert "AUTOMATED_CONTEXT" in str(excinfo.value)


@pytest.mark.parametrize("marker", ["CI", "GITHUB_ACTIONS", "BUILD_ID", "TF_BUILD"])
def test_ci_environments_are_refused(marker: str) -> None:
    with pytest.raises(H.SafeHarnessError) as excinfo:
        H.authorize_live_run(
            argv=("--private-live-run",),
            env={"AWS_PROFILE": H.EXPECTED_PROFILE, marker: "1"},
            modules={},
            identity_gate=lambda: None,
        )
    assert "AUTOMATED_CONTEXT" in str(excinfo.value)


def test_an_authorization_cannot_be_forged() -> None:
    """The token is the network gate. If it could be constructed, the gate would be decorative."""
    with pytest.raises(H.SafeHarnessError):
        H.LiveRunAuthorization(object(), H.EXPECTED_PROFILE)


def test_fetching_without_an_authorization_is_refused() -> None:
    with pytest.raises(H.SafeHarnessError):
        H.fetch_table(None, "stocks", (), H.Pacer())


def test_resolving_buckets_without_an_authorization_is_refused() -> None:
    with pytest.raises(H.SafeHarnessError):
        H.resolve_buckets(None)


def test_the_cli_refuses_and_exits_non_zero_without_the_flag() -> None:
    assert H.main([]) == 2


# ---------------------------------------------------------------------------
# Nothing that leaves the process discloses anything
# ---------------------------------------------------------------------------


def test_a_url_with_a_query_string_never_survives_redaction() -> None:
    message = H.redact(
        "GET https://api.sharadar.com/v1.0/data/stocks"
        "?api_key=synthetic-probe-alpha&ticker=AAPL failed"
    )
    assert "sharadar.com" not in message
    assert "api_key=synthetic-probe-alpha" not in message
    assert "synthetic-probe-alpha" not in message
    assert "ticker=AAPL" not in message


@pytest.mark.parametrize(
    "secret",
    [
        "synthetic-probe-alpha",
        "synthetic-probe-beta",
        "test-api-key",
        "synthetic-arbitrary-value",
    ],
)
def test_an_arbitrary_api_key_value_is_redacted(secret: str) -> None:
    assert secret not in H.redact(f"api_key={secret}")


def test_a_bare_query_string_is_redacted() -> None:
    assert "AAPL" not in H.redact("?ticker=AAPL&format=csv")


def test_the_request_url_is_never_part_of_an_http_error() -> None:
    """A vendor error page and the request URL must both stay out of the exception."""
    url = "https://api.sharadar.com/v1.0/data/stocks?api_key=synthetic-probe-gamma&ticker=AAPL"
    body = "<html>vendor error page mentioning synthetic-probe-gamma and row data</html>"

    class _Body:
        def read(self) -> bytes:
            raise AssertionError("the response body must never be read on an error path")

    def opener(_request: Any, _timeout: float) -> Any:
        raise urllib.error.HTTPError(url, 403, body, {}, _Body())  # type: ignore[arg-type]

    with pytest.raises(H.SafeHarnessError) as excinfo:
        H.fetch_table(_grant(), "stocks", (("ticker", "AAPL"),), H.Pacer(), opener=opener)

    rendered = str(excinfo.value)
    assert "HTTP_AUTHORIZATION_REFUSED" in rendered
    assert "stocks" in rendered
    for forbidden in ("synthetic-probe-gamma", "sharadar.com", "vendor error page", "html", url):
        assert forbidden not in rendered


def test_a_server_error_body_never_reaches_the_exception() -> None:
    def opener(_request: Any, _timeout: float) -> Any:
        raise urllib.error.HTTPError(
            "https://api.sharadar.com/v1.0/data/actions?api_key=synthetic-probe-delta",
            500,
            # Deliberately not shaped like a CSV data row: the repository guard that
            # refuses committed vendor rows would otherwise flag this probe.
            "SYNTHETIC-BODY-CONTENT-THAT-MUST-NOT-ESCAPE",
            {},  # type: ignore[arg-type]
            None,
        )

    with pytest.raises(H.SafeHarnessError) as excinfo:
        H.fetch_table(_grant(), "actions", (), H.Pacer(), opener=opener)
    assert "SYNTHETIC-BODY-CONTENT-THAT-MUST-NOT-ESCAPE" not in str(excinfo.value)
    assert "HTTP_SERVER_ERROR" in str(excinfo.value)


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (401, "HTTP_AUTHORIZATION_REFUSED"),
        (403, "HTTP_AUTHORIZATION_REFUSED"),
        (404, "HTTP_ENDPOINT_NOT_FOUND"),
        (429, "HTTP_RATE_LIMITED"),
        (418, "HTTP_CLIENT_ERROR"),
        (503, "HTTP_SERVER_ERROR"),
        (302, "HTTP_UNEXPECTED_STATUS"),
    ],
)
def test_http_statuses_become_sanitized_categories(status: int, category: str) -> None:
    assert H.classify_http_status(status) == category


def test_the_console_says_nothing_about_the_provider() -> None:
    outcome = H.HarnessOutcome(ok=True, report_path=Path(".runtime/phase3/sharadar/report.html"))
    rendered = "\n".join(H.console_lines(outcome))
    for forbidden in (
        *H.RECOMMENDATIONS,
        *H.STATUSES,
        "P1",
        "P9",
        BUCKETS.licensed,
        BUCKETS.control,
        "sharadar.com",
        "api_key",
    ):
        assert forbidden not in rendered
    assert "PRIVATE QUALIFICATION RUN COMPLETE" in rendered
    assert "Do not paste it into an AI session" in rendered


def test_the_console_still_names_the_report_and_the_prohibition_on_failure() -> None:
    outcome = H.HarnessOutcome(
        ok=False, report_path=Path(".runtime/phase3/sharadar/report.html"), retained_raw=2
    )
    rendered = "\n".join(H.console_lines(outcome))
    assert "INCOMPLETE" in rendered
    assert "retained locally for re-upload: 2" in rendered
    assert not any(recommendation in rendered for recommendation in H.RECOMMENDATIONS)


# ---------------------------------------------------------------------------
# The exit code carries no verdict
# ---------------------------------------------------------------------------


def test_the_outcome_object_has_no_field_that_could_carry_a_recommendation() -> None:
    fields = set(H.HarnessOutcome.__dataclass_fields__)
    assert fields == {"ok", "report_path", "retained_raw"}


def test_a_successful_run_exits_zero_whatever_the_private_conclusion_is() -> None:
    """The disclosure channel this closes: an exit code readable from a log or a transcript."""
    outcome = H.HarnessOutcome(ok=True, report_path=Path("r.html"))
    assert H.operational_exit_code(outcome) == 0
    assert H.operational_exit_code(H.HarnessOutcome(ok=False, report_path=Path("r.html"))) == 1


def test_the_exit_code_function_never_mentions_a_recommendation() -> None:
    """Structural: no expression in it can reach a verdict constant."""
    tree = ast.parse(HARNESS_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in {
            "operational_exit_code",
            "console_lines",
        }:
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            constants = {
                c.value
                for c in ast.walk(node)
                if isinstance(c, ast.Constant) and isinstance(c.value, str)
            }
            assert not names & {"PROCEED", "HOLD", "REJECT", "RECOMMENDATIONS"}
            assert not constants & set(H.RECOMMENDATIONS)


# ---------------------------------------------------------------------------
# Pacing
# ---------------------------------------------------------------------------


def test_the_first_request_is_not_delayed() -> None:
    pacer = H.Pacer(min_interval=1.0, clock=lambda: 100.0, sleeper=lambda _s: None)
    assert pacer.wait() == 0.0


def test_a_second_immediate_request_waits_the_full_interval() -> None:
    slept: list[float] = []
    pacer = H.Pacer(min_interval=1.0, clock=lambda: 100.0, sleeper=slept.append)
    pacer.wait()
    assert pacer.wait() == pytest.approx(1.0)
    assert slept == [pytest.approx(1.0)]


def test_a_request_after_the_interval_has_elapsed_does_not_wait() -> None:
    ticks = iter([100.0, 102.5])
    slept: list[float] = []
    pacer = H.Pacer(min_interval=1.0, clock=lambda: next(ticks), sleeper=slept.append)
    pacer.wait()
    assert pacer.wait() == 0.0
    assert slept == []


def test_the_default_pace_is_at_most_one_request_per_second() -> None:
    assert H.MIN_REQUEST_INTERVAL_SECONDS >= 1.0


def test_the_fetcher_paces_before_it_opens_anything() -> None:
    order: list[str] = []

    class _RecordingPacer:
        """A stand-in, not a subclass: the harness needs only ``wait()``."""

        def wait(self) -> float:
            order.append("paced")
            return 0.0

    def opener(_request: Any, _timeout: float) -> Any:
        order.append("opened")
        raise urllib.error.URLError("unreachable")

    with pytest.raises(H.SafeHarnessError):
        H.fetch_table(_grant(), "stocks", (), _RecordingPacer(), opener=opener)
    assert order == ["paced", "opened"]


def test_the_request_inventory_is_small_fixed_and_single_ticker() -> None:
    tables = [table for table, _ in H.REQUEST_INVENTORY]
    assert tables == ["tickers", "stocks", "actions", "fundamentals", "events"]
    for _, params in H.REQUEST_INVENTORY:
        assert dict(params) == {"ticker": H.SAMPLE_TICKER}


def test_the_user_agent_is_deterministic_and_identifies_the_project() -> None:
    assert H.USER_AGENT == "KalpaMani-Personal-Research/phase3-qualification"


def test_only_the_vendor_published_public_test_key_is_used() -> None:
    assert H.PUBLIC_TEST_API_KEY == "test-api-key"
    assert "api_key=test-api-key" in H.build_request_url("stocks", (("ticker", "AAPL"),))


def test_every_request_is_https() -> None:
    for table, params in H.REQUEST_INVENTORY:
        assert H.build_request_url(table, params).startswith("https://")


# ---------------------------------------------------------------------------
# Content addressing and object keys
# ---------------------------------------------------------------------------


def test_the_payload_hash_is_deterministic() -> None:
    payload = fx.STOCKS_EXCLUSIVE_CSV.encode("utf-8")
    assert H.content_address(payload) == H.content_address(payload)
    assert H.content_address(payload) != H.content_address(payload + b"x")
    assert H.content_address(payload).startswith("sha256/")


def test_the_content_addressed_object_key_is_deterministic() -> None:
    address = H.content_address(b"synthetic")
    assert H.raw_object_key("RUN-1", address) == H.raw_object_key("RUN-1", address)
    assert H.raw_object_key("RUN-1", address) != H.raw_object_key("RUN-2", address)


def test_raw_and_report_keys_both_sit_under_the_qualification_prefix() -> None:
    address = H.content_address(b"synthetic")
    assert H.raw_object_key("RUN-1", address).startswith("qualification/sharadar/RUN-1/")
    assert H.private_report_object_key("RUN-1", "r.html").startswith(
        "qualification/sharadar/RUN-1/private-report/"
    )


def test_the_run_id_is_derived_from_the_clock_not_from_a_random_source() -> None:
    moment = datetime(2026, 8, 27, 14, 5, 9, tzinfo=UTC)
    assert H.make_run_id(moment) == "20260827T140509Z"


# ---------------------------------------------------------------------------
# Licensed, never control
# ---------------------------------------------------------------------------


def test_the_licensed_bucket_is_the_only_accepted_destination() -> None:
    assert H.assert_licensed_destination(BUCKETS.licensed, BUCKETS) == BUCKETS.licensed


def test_writing_qualification_material_to_the_control_bucket_is_refused() -> None:
    """The control bucket is outside the deletion surface. Evidence must not land there."""
    with pytest.raises(H.SafeHarnessError) as excinfo:
        H.assert_licensed_destination(BUCKETS.control, BUCKETS)
    assert "CONTROL_BUCKET_IS_NOT_A_QUALIFICATION_DESTINATION" in str(excinfo.value)


def test_an_unknown_destination_bucket_is_refused() -> None:
    with pytest.raises(H.SafeHarnessError):
        H.assert_licensed_destination("some-other-bucket", BUCKETS)


# ---------------------------------------------------------------------------
# Staging, upload and local deletion
# ---------------------------------------------------------------------------


def test_a_staged_payload_is_deleted_once_it_is_in_the_licensed_bucket(tmp_path: Path) -> None:
    staged = H.stage_payload(tmp_path, "stocks", fx.STOCKS_EXCLUSIVE_CSV.encode("utf-8"))
    assert staged.path.is_file()

    seen: list[tuple[str, str]] = []

    def put(bucket: str, key: str, _body: Path, _profile: str) -> None:
        seen.append((bucket, key))

    uploaded = H.upload_staged([staged], "RUN-1", BUCKETS, "profile", put=put)
    deleted, retained = H.purge_uploaded(uploaded)

    assert seen == [(BUCKETS.licensed, H.raw_object_key("RUN-1", staged.address))]
    assert (deleted, retained) == (1, 0)
    assert not staged.path.exists()


def test_a_failed_upload_retains_the_local_payload_for_recovery(tmp_path: Path) -> None:
    """Licensed evidence must survive a transient fault. Losing it is worse than a duplicate."""
    staged = H.stage_payload(tmp_path, "stocks", fx.STOCKS_EXCLUSIVE_CSV.encode("utf-8"))

    def put(_bucket: str, _key: str, _body: Path, _profile: str) -> None:
        raise H.SafeHarnessError("upload", "UPLOAD_REFUSED_BY_AWS")

    uploaded = H.upload_staged([staged], "RUN-1", BUCKETS, "profile", put=put)
    deleted, retained = H.purge_uploaded(uploaded)

    assert (deleted, retained) == (0, 1)
    assert staged.path.is_file()
    assert staged.path.read_bytes() == fx.STOCKS_EXCLUSIVE_CSV.encode("utf-8")


def test_one_failed_upload_does_not_delete_the_others_or_abort_the_run(tmp_path: Path) -> None:
    good = H.stage_payload(tmp_path, "stocks", b"a,b\n1,2\n")
    bad = H.stage_payload(tmp_path, "actions", b"c,d\n3,4\n")

    def put(_bucket: str, key: str, _body: Path, _profile: str) -> None:
        if key.endswith(bad.address):
            raise H.SafeHarnessError("upload", "UPLOAD_REFUSED_BY_AWS")

    uploaded = H.upload_staged([good, bad], "RUN-1", BUCKETS, "profile", put=put)
    deleted, retained = H.purge_uploaded(uploaded)

    assert (deleted, retained) == (1, 1)
    assert not good.path.exists()
    assert bad.path.is_file()


# ---------------------------------------------------------------------------
# P1-P9 -- the anti-optimism guarantees
# ---------------------------------------------------------------------------


def test_every_provider_test_is_evaluated() -> None:
    findings = H.evaluate_all(_samples(fx.COHERENT_SAMPLE))
    assert tuple(f.test_id for f in findings) == H.TEST_IDS


def test_p2_can_never_pass_on_the_public_sample() -> None:
    """The strongest form of the guarantee: the evaluator has no data input to pass on."""
    assert H.evaluate_p2().status == H.NOT_TESTABLE_WITH_PUBLIC_SAMPLE
    assert H.STATUS_CEILING["P2"] == frozenset({H.NOT_TESTABLE_WITH_PUBLIC_SAMPLE})


@pytest.mark.parametrize("test_id", ["P2", "P4", "P6", "P9"])
def test_the_undecidable_tests_take_no_sample_argument(test_id: str) -> None:
    """A function with no data parameter cannot be talked into a pass by a fixture."""
    evaluator = getattr(H, f"evaluate_{test_id.lower()}")
    assert evaluator.__code__.co_argcount == 0


def test_p7_and_p8_stay_deferred_even_when_the_sample_looks_helpful() -> None:
    generous = dict(fx.COHERENT_SAMPLE)
    generous["events"] = fx.EVENTS_WITH_TIME_CSV
    samples = _samples(generous)
    assert H.evaluate_p7(samples).status == H.DEFERRED
    assert H.evaluate_p8(samples).status == H.DEFERRED


def test_p8_remains_deferred_with_a_time_column_present() -> None:
    """A time-like column would be the most tempting reason to call P8 answered. It is not."""
    samples = _samples({"events": fx.EVENTS_WITH_TIME_CSV})
    finding = H.evaluate_p8(samples)
    assert finding.status == H.DEFERRED
    assert finding.attributes["deferred_to"] == "Phase 3B / EDGAR"


def test_p9_never_claims_public_pit_eligibility() -> None:
    finding = H.evaluate_p9()
    assert finding.attributes["eligible_profile"] == "PROVIDER_REALISTIC_PIT"
    assert finding.attributes["information_origin"] == "PROVIDER_DERIVED"
    assert finding.attributes["eligible_profile"] != H.FORBIDDEN_P9_PROFILE


def test_a_forged_p9_claiming_public_pit_is_refused() -> None:
    findings = list(H.evaluate_all(_samples(fx.COHERENT_SAMPLE)))
    index = next(i for i, f in enumerate(findings) if f.test_id == "P9")
    findings[index] = H.Finding(
        test_id="P9",
        title="Bar construction and origin",
        status=H.DOCUMENTATION_RESOLVED,
        attributes={
            "information_origin": "AUTHORITATIVE_PUBLIC",
            "eligible_profile": H.FORBIDDEN_P9_PROFILE,
        },
    )
    with pytest.raises(H.SafeHarnessError) as excinfo:
        H.validate_findings(findings)
    assert "P9_PROFILE_MUST_REMAIN_PROVIDER_REALISTIC" in str(excinfo.value)


def test_a_forged_p2_pass_is_refused() -> None:
    findings = list(H.evaluate_all(_samples(fx.COHERENT_SAMPLE)))
    index = next(i for i, f in enumerate(findings) if f.test_id == "P2")
    findings[index] = H.Finding(test_id="P2", title="Delisted coverage", status=H.TESTED)
    with pytest.raises(H.SafeHarnessError) as excinfo:
        H.validate_findings(findings)
    assert "STATUS_ABOVE_CEILING_P2" in str(excinfo.value)


@pytest.mark.parametrize("test_id", ["P7", "P8"])
def test_a_forged_p7_or_p8_pass_is_refused(test_id: str) -> None:
    findings = list(H.evaluate_all(_samples(fx.COHERENT_SAMPLE)))
    index = next(i for i, f in enumerate(findings) if f.test_id == test_id)
    findings[index] = H.Finding(test_id=test_id, title="forged", status=H.TESTED)
    with pytest.raises(H.SafeHarnessError) as excinfo:
        H.validate_findings(findings)
    assert f"STATUS_ABOVE_CEILING_{test_id}" in str(excinfo.value)


def test_a_forged_p1_claiming_exact_provider_availability_is_refused() -> None:
    findings = list(H.evaluate_all(_samples(fx.COHERENT_SAMPLE)))
    index = next(i for i, f in enumerate(findings) if f.test_id == "P1")
    findings[index] = H.Finding(
        test_id="P1",
        title="Provider availability",
        status=H.PARTIALLY_TESTED,
        attributes={"gap_policy": "EXACT"},
    )
    with pytest.raises(H.SafeHarnessError) as excinfo:
        H.validate_findings(findings)
    assert "P1_GAP_POLICY_MUST_REMAIN_BOUND" in str(excinfo.value)


def test_a_p6_that_drops_the_revision_chronology_limitation_is_refused() -> None:
    findings = list(H.evaluate_all(_samples(fx.COHERENT_SAMPLE)))
    index = next(i for i, f in enumerate(findings) if f.test_id == "P6")
    findings[index] = H.Finding(
        test_id="P6", title="Restatements", status=H.DOCUMENTATION_RESOLVED, limitations=()
    )
    with pytest.raises(H.SafeHarnessError) as excinfo:
        H.validate_findings(findings)
    assert "P6_MUST_RETAIN_REVISION_CHRONOLOGY_LIMITATION" in str(excinfo.value)


def test_a_missing_finding_is_refused() -> None:
    findings = [f for f in H.evaluate_all(_samples(fx.COHERENT_SAMPLE)) if f.test_id != "P5"]
    with pytest.raises(H.SafeHarnessError) as excinfo:
        H.validate_findings(findings)
    assert "MISSING_FINDINGS_P5" in str(excinfo.value)


def test_every_evaluated_finding_sits_inside_its_ceiling() -> None:
    for payloads in ({}, fx.COHERENT_SAMPLE, {"stocks": fx.STOCKS_NO_SPLIT_CSV}):
        H.validate_findings(H.evaluate_all(_samples(payloads)))


def test_p1_records_bound_and_never_claims_a_test_it_cannot_run() -> None:
    finding = H.evaluate_p1(_samples(fx.COHERENT_SAMPLE))
    assert finding.status in H.STATUS_CEILING["P1"]
    assert finding.status != H.TESTED
    assert finding.attributes["gap_policy"] == "BOUND"


def test_p1_is_inconclusive_when_the_column_it_needs_is_absent() -> None:
    finding = H.evaluate_p1(_samples({"stocks": fx.STOCKS_NO_LASTUPDATED_CSV}))
    assert finding.status == H.INCONCLUSIVE


def test_p3_stays_documentation_resolved_and_keeps_the_approximation_token() -> None:
    finding = H.evaluate_p3(_samples(fx.COHERENT_SAMPLE))
    assert finding.status == H.DOCUMENTATION_RESOLVED
    assert "CORPORATE_ACTION_ANNOUNCE_APPROXIMATED" in finding.limitations


def test_p4_is_documentation_resolved_and_takes_no_sample() -> None:
    """The tickers table is a documented snapshot, so no sample can settle P4 either way."""
    finding = H.evaluate_p4()
    assert finding.status == H.DOCUMENTATION_RESOLVED
    assert finding.attributes["source_shape"] == "SNAPSHOT"
    assert H.evaluate_p4.__code__.co_argcount == 0


def test_p4_always_carries_the_static_classification_limitation() -> None:
    assert "CLASSIFICATION_STATIC" in H.evaluate_p4().limitations
    assert H.STATUS_CEILING["P4"] == frozenset({H.DOCUMENTATION_RESOLVED})


@pytest.mark.parametrize(
    "tickers",
    [fx.TICKERS_CSV, fx.TICKERS_MULTI_TABLE_CSV, fx.TICKERS_RECLASSIFIED_CSV],
)
def test_no_arrangement_of_snapshot_rows_removes_the_static_limitation(tickers: str) -> None:
    """The correction this pins.

    An earlier version read *differing* sector/industry values across snapshot rows as a
    dated series and dropped ``CLASSIFICATION_STATIC``. Differing values in a snapshot mean
    the snapshot disagrees with itself; they carry no date and cannot say when anything
    changed. ``TICKERS_RECLASSIFIED_CSV`` is exactly that shape, and it must change nothing.
    """
    findings = H.evaluate_all(_samples({"tickers": tickers}))
    p4 = next(f for f in findings if f.test_id == "P4")
    assert "CLASSIFICATION_STATIC" in p4.limitations
    assert p4.status == H.DOCUMENTATION_RESOLVED


def test_no_sample_can_promote_p4_to_tested() -> None:
    for payloads in ({}, fx.COHERENT_SAMPLE, {"tickers": fx.TICKERS_RECLASSIFIED_CSV}):
        findings = H.evaluate_all(_samples(payloads))
        p4 = next(f for f in findings if f.test_id == "P4")
        assert p4.status != H.TESTED


def test_a_forged_p4_pass_is_refused() -> None:
    findings = list(H.evaluate_all(_samples(fx.COHERENT_SAMPLE)))
    index = next(i for i, f in enumerate(findings) if f.test_id == "P4")
    findings[index] = H.Finding(
        test_id="P4",
        title="Classification history",
        status=H.TESTED,
        limitations=("CLASSIFICATION_STATIC",),
    )
    with pytest.raises(H.SafeHarnessError) as excinfo:
        H.validate_findings(findings)
    assert "STATUS_ABOVE_CEILING_P4" in str(excinfo.value)


def test_a_p4_that_drops_the_static_limitation_is_refused() -> None:
    findings = list(H.evaluate_all(_samples(fx.COHERENT_SAMPLE)))
    index = next(i for i, f in enumerate(findings) if f.test_id == "P4")
    findings[index] = H.Finding(
        test_id="P4",
        title="Classification history",
        status=H.DOCUMENTATION_RESOLVED,
        limitations=(),
    )
    with pytest.raises(H.SafeHarnessError) as excinfo:
        H.validate_findings(findings)
    assert "P4_MUST_RETAIN_CLASSIFICATION_STATIC" in str(excinfo.value)


# ---------------------------------------------------------------------------
# P5 -- the split reconciliation
# ---------------------------------------------------------------------------


def test_the_exclusive_action_date_convention_is_identified() -> None:
    samples = _samples({"stocks": fx.STOCKS_EXCLUSIVE_CSV, "actions": fx.ACTIONS_CSV})
    result = H.reconcile_split_adjustment(
        samples["stocks"].rows, H.extract_splits(samples["actions"])
    )
    assert result.status == H.TESTED
    assert result.convention == H.EXCLUSIVE_OF_ACTION_DATE


def test_the_inclusive_action_date_convention_is_identified() -> None:
    samples = _samples({"stocks": fx.STOCKS_INCLUSIVE_CSV, "actions": fx.ACTIONS_CSV})
    result = H.reconcile_split_adjustment(
        samples["stocks"].rows, H.extract_splits(samples["actions"])
    )
    assert result.status == H.TESTED
    assert result.convention == H.INCLUSIVE_OF_ACTION_DATE


def test_an_irreconcilable_series_is_never_reported_as_reconciled() -> None:
    samples = _samples({"stocks": fx.STOCKS_IRRECONCILABLE_CSV, "actions": fx.ACTIONS_CSV})
    result = H.reconcile_split_adjustment(
        samples["stocks"].rows, H.extract_splits(samples["actions"])
    )
    assert result.status == H.INCONCLUSIVE
    assert result.convention == H.CONVENTION_UNRESOLVED
    assert result.worst_relative_deviation > H.SPLIT_TOLERANCE


def test_a_range_with_no_split_is_not_a_pass() -> None:
    """Adjusted equals unadjusted trivially here; the adjustment method is untested."""
    samples = _samples({"stocks": fx.STOCKS_NO_SPLIT_CSV, "actions": fx.ACTIONS_NO_SPLIT_CSV})
    result = H.reconcile_split_adjustment(
        samples["stocks"].rows, H.extract_splits(samples["actions"])
    )
    assert result.status == H.PARTIALLY_TESTED
    assert result.splits_in_range == 0


def test_dividends_are_not_folded_into_the_split_factor() -> None:
    splits = H.extract_splits(_samples({"actions": fx.ACTIONS_CSV})["actions"])
    assert splits == [("2020-06-01", 2.0)]


def test_p5_is_inconclusive_when_the_split_limb_fails() -> None:
    samples = _samples({"stocks": fx.STOCKS_IRRECONCILABLE_CSV, "actions": fx.ACTIONS_CSV})
    assert H.evaluate_p5(samples).status == H.INCONCLUSIVE


# ---------------------------------------------------------------------------
# P5 -- the cash-dividend limb, against the vendor's published ratio
# ---------------------------------------------------------------------------


def test_the_action_vocabulary_is_observed_not_assumed() -> None:
    actions = _samples({"actions": fx.ACTIONS_COHERENT_CSV})["actions"]
    assert H.observed_action_vocabulary(actions) == ("dividend", "split")


def test_an_unambiguous_dividend_literal_is_identified() -> None:
    vocabulary = ("dividend", "split")
    assert H.infer_action_literal(vocabulary, "dividend", exclude="stock") == "dividend"


def test_a_stock_dividend_does_not_make_the_cash_literal_ambiguous() -> None:
    vocabulary = ("dividend", "split", "stockdividend")
    assert H.infer_action_literal(vocabulary, "dividend", exclude="stock") == "dividend"


def test_an_ambiguous_vocabulary_refuses_to_pick_a_favourite() -> None:
    vocabulary = ("dividend", "specialdividend", "split")
    assert H.infer_action_literal(vocabulary, "dividend", exclude="stock") is None


def test_an_absent_literal_is_not_invented() -> None:
    assert H.infer_action_literal(("split",), "dividend") is None


def test_an_absent_literal_is_distinguished_from_an_ambiguous_one() -> None:
    """Collapsing these two would turn a quiet sample into a provider finding.

    No dividend action in the window means the limb was never exercised. Several
    dividend-like literals mean the harness must not choose. Only the second is a reason to
    report INCONCLUSIVE, and an earlier revision reported both that way.
    """
    _, absent = H.classify_action_literal(("split",), "dividend")
    _, ambiguous = H.classify_action_literal(("dividend", "specialdividend"), "dividend")
    _, identified = H.classify_action_literal(("dividend", "split"), "dividend")

    assert absent == H.LITERAL_ABSENT
    assert ambiguous == H.LITERAL_AMBIGUOUS
    assert identified == H.LITERAL_IDENTIFIED
    assert len({absent, ambiguous, identified}) == 3


def test_the_dividend_limb_pins_both_the_convention_and_the_denomination() -> None:
    """The fixture discriminates all four candidate models, so the answer is observed.

    The vendor publishes the ratio but states neither which price series the dividend is
    denominated in nor whether an action dated D applies at D itself. Naming a single model
    is therefore a measurement, not an assumption.
    """
    finding = H.evaluate_p5(_samples(fx.COHERENT_SAMPLE))
    assert finding.attributes["dividend_limb"] == H.TESTED
    assert finding.attributes["dividend_model"] == "EXCLUSIVE_UNADJUSTED"


def test_the_dividend_limb_is_inconclusive_when_the_vocabulary_is_ambiguous() -> None:
    samples = _samples(
        {
            "stocks": fx.STOCKS_COHERENT_CSV,
            "actions": fx.ACTIONS_AMBIGUOUS_DIVIDEND_CSV,
        }
    )
    finding = H.evaluate_p5(samples)
    assert finding.attributes["dividend_limb"] == H.INCONCLUSIVE
    assert finding.status == H.INCONCLUSIVE


def test_the_dividend_limb_is_inconclusive_when_nothing_reconciles() -> None:
    samples = _samples(
        {
            "stocks": fx.STOCKS_DIVIDEND_IRRECONCILABLE_CSV,
            "actions": fx.ACTIONS_COHERENT_CSV,
        }
    )
    assert H.evaluate_p5(samples).attributes["dividend_limb"] == H.INCONCLUSIVE


def test_a_range_with_no_dividend_is_not_a_dividend_pass() -> None:
    """Trivial agreement proves nothing about the mechanism."""
    samples = _samples({"stocks": fx.STOCKS_NO_DIVIDEND_CSV, "actions": fx.ACTIONS_SPLIT_ONLY_CSV})
    finding = H.evaluate_p5(samples)
    assert finding.attributes["dividend_limb"] == H.PARTIALLY_TESTED
    assert finding.status == H.PARTIALLY_TESTED


def test_an_unexplained_divergence_is_inconclusive_not_absent() -> None:
    """close and closeadj differ with no event that could explain it. That is a finding."""
    samples = _samples(
        {
            "stocks": fx.STOCKS_UNEXPLAINED_DIVERGENCE_CSV,
            "actions": fx.ACTIONS_SPLIT_ONLY_CSV,
        }
    )
    assert H.evaluate_p5(samples).attributes["dividend_limb"] == H.INCONCLUSIVE


# ---------------------------------------------------------------------------
# P5 -- the spinoff limb, which can never be exercised here
# ---------------------------------------------------------------------------


def test_the_spinoff_limb_does_not_run_when_no_spinoff_is_present() -> None:
    finding = H.evaluate_p5(_samples(fx.COHERENT_SAMPLE))
    assert finding.attributes["spinoff_limb"] == H.NOT_EXERCISED
    assert "SPINOFF_ADJUSTMENT_UNEXERCISED" in finding.limitations


def test_a_spinoff_in_range_makes_the_limb_inconclusive() -> None:
    """Its ratio needs the spun-off entity's opening price, which this sample cannot hold."""
    samples = _samples({"stocks": fx.STOCKS_COHERENT_CSV, "actions": fx.ACTIONS_WITH_SPINOFF_CSV})
    finding = H.evaluate_p5(samples)
    assert finding.attributes["spinoff_limb"] == H.INCONCLUSIVE
    assert finding.status == H.INCONCLUSIVE
    assert "SPINOFF_ADJUSTMENT_INPUTS_UNAVAILABLE" in finding.limitations


def test_the_spinoff_limb_is_never_tested_whatever_the_sample() -> None:
    for payloads in (
        {},
        fx.COHERENT_SAMPLE,
        {"stocks": fx.STOCKS_COHERENT_CSV, "actions": fx.ACTIONS_WITH_SPINOFF_CSV},
        {"stocks": fx.STOCKS_NO_DIVIDEND_CSV, "actions": fx.ACTIONS_SPLIT_ONLY_CSV},
    ):
        finding = H.evaluate_p5(_samples(payloads))
        assert finding.attributes["spinoff_limb"] != H.TESTED


def test_a_forged_tested_spinoff_limb_is_refused() -> None:
    findings = list(H.evaluate_all(_samples(fx.COHERENT_SAMPLE)))
    index = next(i for i, f in enumerate(findings) if f.test_id == "P5")
    findings[index] = H.Finding(
        test_id="P5",
        title="Adjusted/raw reconciliation",
        status=H.PARTIALLY_TESTED,
        attributes={
            "split_limb": H.TESTED,
            "dividend_limb": H.TESTED,
            "spinoff_limb": H.TESTED,
        },
    )
    with pytest.raises(H.SafeHarnessError) as excinfo:
        H.validate_findings(findings)
    assert "P5_SPINOFF_LIMB_CANNOT_BE_TESTED" in str(excinfo.value)


def test_a_p5_missing_a_limb_status_is_refused() -> None:
    findings = list(H.evaluate_all(_samples(fx.COHERENT_SAMPLE)))
    index = next(i for i, f in enumerate(findings) if f.test_id == "P5")
    findings[index] = H.Finding(
        test_id="P5",
        title="Adjusted/raw reconciliation",
        status=H.PARTIALLY_TESTED,
        attributes={"split_limb": H.TESTED, "dividend_limb": H.TESTED},
    )
    with pytest.raises(H.SafeHarnessError) as excinfo:
        H.validate_findings(findings)
    assert "P5_LIMB_STATUS_MISSING" in str(excinfo.value)


def test_p5_never_reaches_tested_even_when_every_runnable_limb_passes() -> None:
    """The whole point of the ceiling: a mechanism never exercised end to end is not proven."""
    finding = H.evaluate_p5(_samples(fx.COHERENT_SAMPLE))
    assert finding.attributes["split_limb"] == H.TESTED
    assert finding.attributes["dividend_limb"] == H.TESTED
    assert finding.status == H.PARTIALLY_TESTED
    assert H.TESTED not in H.STATUS_CEILING["P5"]


def test_not_exercised_is_a_limb_status_and_never_a_finding_status() -> None:
    """A limb the sample never ran must not be expressible as a provider-test result."""
    assert H.NOT_EXERCISED in H.LIMB_STATUSES
    assert H.NOT_EXERCISED not in H.STATUSES
    for ceiling in H.STATUS_CEILING.values():
        assert H.NOT_EXERCISED not in ceiling


# ---------------------------------------------------------------------------
# Parsing failures degrade honestly
# ---------------------------------------------------------------------------


def test_a_malformed_payload_is_recorded_not_raised() -> None:
    sample = H.parse_csv_payload("stocks", fx.MALFORMED_PAYLOAD, "sha256/x")
    assert not sample.usable
    assert sample.parse_error is not None


def test_a_malformed_payload_produces_no_pass_anywhere() -> None:
    samples = {"stocks": H.parse_csv_payload("stocks", fx.MALFORMED_PAYLOAD, "sha256/x")}
    findings = H.evaluate_all(samples)
    H.validate_findings(findings)
    assert {f.status for f in findings} <= H.STATUSES
    assert all(f.status != H.TESTED for f in findings if f.test_id in {"P1", "P5"})


# ---------------------------------------------------------------------------
# The private recommendation stays private
# ---------------------------------------------------------------------------


def test_the_recommendation_is_one_of_the_declared_values() -> None:
    assert H.private_recommendation(H.evaluate_all(_samples(fx.COHERENT_SAMPLE))) in (
        H.RECOMMENDATIONS
    )


def test_a_vendor_series_that_does_not_reconcile_produces_a_reject() -> None:
    samples = _samples({"stocks": fx.STOCKS_IRRECONCILABLE_CSV, "actions": fx.ACTIONS_CSV})
    assert H.private_recommendation(H.evaluate_all(samples)) == H.REJECT


def test_missing_evidence_holds_rather_than_proceeding() -> None:
    assert H.private_recommendation(H.evaluate_all({})) == H.HOLD


def test_missing_evidence_never_rejects_the_provider() -> None:
    """A table we could not retrieve says nothing about the vendor's data.

    REJECT is reserved for the vendor's own two price series contradicting each other, which
    requires having compared them. An earlier revision reached REJECT from an empty sample,
    because "not retrieved" and "failed to reconcile" shared one limb status.
    """
    findings = H.evaluate_all({})
    p5 = next(f for f in findings if f.test_id == "P5")
    assert p5.attributes["split_limb"] == H.NOT_EXERCISED
    assert p5.attributes["evidence"] == "STOCKS_NOT_RETRIEVED"
    assert H.private_recommendation(findings) == H.HOLD


def test_a_genuine_reconciliation_failure_still_rejects() -> None:
    """Without this, the test above could pass on a function that never rejects at all."""
    samples = _samples({"stocks": fx.STOCKS_IRRECONCILABLE_CSV, "actions": fx.ACTIONS_CSV})
    assert H.private_recommendation(H.evaluate_all(samples)) == H.REJECT


def test_a_coherent_sample_can_reach_proceed() -> None:
    """Without this, the two tests above could pass on a function that always says HOLD."""
    assert H.private_recommendation(H.evaluate_all(_samples(fx.COHERENT_SAMPLE))) == H.PROCEED


# ---------------------------------------------------------------------------
# End to end, with every boundary injected
# ---------------------------------------------------------------------------


def _run(tmp_path: Path, payloads: dict[str, str], **kwargs: Any) -> tuple[Any, list[str]]:
    keys: list[str] = []

    def fetcher(_auth: Any, table: str, _params: Any, _pacer: Any) -> bytes:
        if table not in payloads:
            raise H.SafeHarnessError("fetch", "HTTP_ENDPOINT_NOT_FOUND", table)
        return payloads[table].encode("utf-8")

    def put(bucket: str, key: str, _body: Path, _profile: str) -> None:
        assert bucket == BUCKETS.licensed, "qualification material must go to the licensed bucket"
        keys.append(key)

    outcome = H.run_private_qualification(
        _grant(),
        BUCKETS,
        datetime(2026, 8, 27, 9, 0, 0, tzinfo=UTC),
        runtime_root=tmp_path,
        fetcher=kwargs.get("fetcher", fetcher),
        put=kwargs.get("put", put),
    )
    return outcome, keys


def test_a_complete_run_stores_everything_under_the_licensed_qualification_prefix(
    tmp_path: Path,
) -> None:
    outcome, keys = _run(tmp_path, dict(fx.COHERENT_SAMPLE))
    assert outcome.ok
    assert len(keys) == len(fx.COHERENT_SAMPLE) + 1
    assert all(key.startswith("qualification/sharadar/20260827T090000Z/") for key in keys)
    assert sum(1 for key in keys if "/private-report/" in key) == 1
    assert sum(1 for key in keys if "/raw/sha256/" in key) == len(fx.COHERENT_SAMPLE)


def test_a_complete_run_leaves_no_raw_vendor_payload_on_the_workstation(tmp_path: Path) -> None:
    outcome, _ = _run(tmp_path, dict(fx.COHERENT_SAMPLE))
    assert outcome.retained_raw == 0
    assert list((tmp_path / "20260827T090000Z" / "raw").glob("*")) == []


def test_the_report_is_written_under_the_private_runtime_area(tmp_path: Path) -> None:
    outcome, _ = _run(tmp_path, dict(fx.COHERENT_SAMPLE))
    assert outcome.report_path.is_file()
    assert outcome.report_path.parent.parent == tmp_path
    assert (tmp_path / H.REPORT_FILENAME).is_file()


def test_the_default_report_location_is_inside_the_git_ignored_runtime_area() -> None:
    assert H.RUNTIME_ROOT.is_relative_to(PROJECT_ROOT / ".runtime")


def test_the_report_carries_the_do_not_disclose_banner(tmp_path: Path) -> None:
    outcome, _ = _run(tmp_path, dict(fx.COHERENT_SAMPLE))
    html = outcome.report_path.read_text(encoding="utf-8")
    for line in H.REPORT_BANNER:
        assert line in html
    assert any(recommendation in html for recommendation in H.RECOMMENDATIONS)


def test_the_report_holds_the_recommendation_that_the_console_withholds(tmp_path: Path) -> None:
    outcome, _ = _run(tmp_path, dict(fx.COHERENT_SAMPLE))
    html = outcome.report_path.read_text(encoding="utf-8")
    console = "\n".join(H.console_lines(outcome))
    private = next(r for r in H.RECOMMENDATIONS if r in html)
    assert private not in console


def test_the_report_does_not_claim_full_history_resolves_p6(tmp_path: Path) -> None:
    """P6 is a modelling limitation, not a coverage one, and no tier fixes it.

    As-reported excludes restatements and most-recent-reported is updated in place, so no
    revision chronology exists at any depth. A report that bundled P6 with P2 as "both need
    Full History" would encourage a purchase on a false premise.
    """
    outcome, _ = _run(tmp_path, dict(fx.COHERENT_SAMPLE))
    html = outcome.report_path.read_text(encoding="utf-8")

    assert "Full History does NOT solve this" in html
    assert "EDGAR / Phase 3B is the required route" in html
    assert "P2 and P6 remain the two structural unknowns" not in html

    # No sentence may pair P6 with Full History as a solution.
    for line in html.splitlines():
        if "P6" in line and "Full History" in line:
            assert "NOT" in line, f"P6 and Full History paired without a refusal: {line}"


def test_the_report_still_tells_the_owner_p2_needs_paid_depth(tmp_path: Path) -> None:
    """The corrected wording must not lose P2's real requirement while fixing P6's."""
    outcome, _ = _run(tmp_path, dict(fx.COHERENT_SAMPLE))
    html = outcome.report_path.read_text(encoding="utf-8")
    assert "delisted coverage" in html.lower()
    assert "Full History depth" in html


def test_a_failed_upload_keeps_the_raw_payload_and_reports_an_operational_failure(
    tmp_path: Path,
) -> None:
    def put(_bucket: str, _key: str, _body: Path, _profile: str) -> None:
        raise H.SafeHarnessError("upload", "UPLOAD_REFUSED_BY_AWS")

    outcome, _ = _run(tmp_path, dict(fx.COHERENT_SAMPLE), put=put)
    assert not outcome.ok
    assert H.operational_exit_code(outcome) == 1
    assert outcome.retained_raw == len(fx.COHERENT_SAMPLE)
    assert list((tmp_path / "20260827T090000Z" / "raw").glob("*"))
    assert outcome.report_path.is_file()


def test_a_partly_unreachable_api_still_produces_a_valid_private_report(tmp_path: Path) -> None:
    payloads = {k: v for k, v in fx.COHERENT_SAMPLE.items() if k != "events"}
    outcome, keys = _run(tmp_path, payloads)
    assert not outcome.ok
    html = outcome.report_path.read_text(encoding="utf-8")
    assert "HTTP_ENDPOINT_NOT_FOUND" in html
    assert sum(1 for key in keys if "/raw/sha256/" in key) == len(payloads)
