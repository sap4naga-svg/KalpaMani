"""Synthetic acceptance tests: the compiled plan and end-to-end production acquisition.

Every run here goes through the accepted bootstrap (binding, input, self-check,
identity, release barrier) and then through the processing executor over
injected fakes: a secrets fake, a provider fake, a ``put_object``-only S3 fake.
No socket, no SDK, no real service. **A passing test here is not AWS
verification.**
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Final

import pytest

from fixtures.production_runtime import (
    BUCKET,
    CANARIES,
    INTERFACE_ID,
    NOW,
    OTHER_PLAN_DIGEST,
    PLAN_DIGEST,
    RUN_ID,
    SUBNET_ID,
    TASK_ARN,
    FakeClientError,
    FakeClock,
    FakeSsm,
    acquisition_input_document,
    binding_document,
    caller_identity,
    compiled_digest,
    compiled_task,
    encode,
    metadata_document,
    revision_arn,
    slice_document,
    task_identity_arn,
)
from kalpamani.data.contracts.vocabulary import AcquisitionMode
from kalpamani.data.ingest.publication import (
    acquisition_claim_key,
    bronze_acquisition_key,
    bronze_payload_key,
)
from kalpamani.data.ingest.sharadar.credentials import SharadarCredential
from kalpamani.data.production.sharadar import plan as pplan
from kalpamani.data.production.sharadar import processing as pp
from kalpamani.data.production.sharadar.identities import (
    LedgerSpentIdentities,
    UnavailableSpentIdentities,
)
from kalpamani.data.production.sharadar.inputs import (
    InputDefect,
    InputError,
    LedgerRow,
    input_digest,
    parse_slice,
)
from kalpamani.data.production.sharadar.locator import (
    Completeness,
    PayloadDisposition,
    ProductionLocatorReader,
    RunLocatorError,
    decode_run_locator,
    validate_run_locator,
)
from kalpamani.data.production.sharadar.outcomes import RunnerOutcome
from kalpamani.data.production.sharadar.parameters import SsmParameterAdapter
from kalpamani.data.production.sharadar.release import build_release_document
from kalpamani.data.production.sharadar.runner import RunnerAdapters
from kalpamani.data.production.sharadar.vocabulary import ProductionActor, constants_for
from kalpamani.data.qualify.sharadar.operations import LocatorPublicationStatus
from kalpamani.data.qualify.sharadar.publication import qualification_payload_key

ACQ: Final = ProductionActor.ACQUISITION
SECRET_ID: Final = "synthetic/production/sharadar"  # noqa: S105 - an identifier, not a secret
SECRET_VALUE: Final = "synthetic-fake-not-a-real-sharadar-key-0009"  # noqa: S105 - announces itself fake


# ---------------------------------------------------------------------------
# The compiled plan
# ---------------------------------------------------------------------------


class TestCompiledPlan:
    def test_the_default_slice_compiles_to_six_canonical_requests(self) -> None:
        plan = pplan.compile_plan(
            parse_slice(slice_document()), acquisition_mode=AcquisitionMode.BACKFILL
        )
        coordinates = [
            (r.ordinal, r.dataset, r.window, r.page_offset, r.page_limit) for r in plan.requests
        ]
        assert coordinates == [
            (0, "actions", "2025-01-01/2025-12-31", 0, 10000),
            (1, "actions", "2025-01-01/2025-12-31", 10000, 10000),
            (2, "tickers", "SNAPSHOT", 0, 10000),
            (3, "tickers", "SNAPSHOT", 10000, 10000),
            (4, "tickers", "SNAPSHOT", 20000, 10000),
            (5, "tickers", "SNAPSHOT", 30000, 10000),
        ]
        assert plan.digest == PLAN_DIGEST and plan.provider_max_attempts == 1
        assert plan.deadline_seconds == 1800.0 and plan.min_request_interval_seconds == 1.0
        assert PLAN_DIGEST not in repr(plan)

    def test_the_digest_is_deterministic_and_sensitive_to_every_coordinate(self) -> None:
        base = compiled_digest()
        assert compiled_digest() == base
        assert (
            compiled_digest(
                slice_document(windows={"actions": "2024-01-01/2024-12-31", "tickers": "SNAPSHOT"})
            )
            != base
        )
        assert compiled_digest(slice_document(max_response_bytes=1024)) != base
        assert compiled_digest(slice_document(acquisition_mode="UPDATE")) != base

    def test_actions_windows_are_cut_into_canonical_years_and_stocks_into_days(self) -> None:
        covered = parse_slice(
            slice_document(
                datasets=["actions", "stocks"],
                windows={"actions": "1998-01-01/2000-06-30", "stocks": "2025-09-01/2025-09-03"},
                request_count=3 * 2 + 3 * 2,
            )
        )
        plan = pplan.compile_plan(covered, acquisition_mode=AcquisitionMode.BACKFILL)
        windows = [r.window for r in plan.requests if r.dataset == "actions"][::2]
        assert windows == [
            "1998-01-01/1999-01-01",
            "1999-01-02/2000-01-02",
            "2000-01-03/2000-06-30",
        ]
        days = [r.window for r in plan.requests if r.dataset == "stocks"][::2]
        assert days == ["2025-09-01/2025-09-01", "2025-09-02/2025-09-02", "2025-09-03/2025-09-03"]

    @pytest.mark.parametrize(
        ("overrides", "mode"),
        [
            ({"request_count": 5}, AcquisitionMode.BACKFILL),  # not what the plan issues
            ({"windows": {"actions": "SNAPSHOT", "tickers": "SNAPSHOT"}}, AcquisitionMode.BACKFILL),
            (
                {
                    "windows": {
                        "actions": "2025-01-01/2025-12-31",
                        "tickers": "2025-01-01/2025-12-31",
                    }
                },
                AcquisitionMode.BACKFILL,
            ),
            (
                {"windows": {"actions": "1997-01-01/1997-12-31", "tickers": "SNAPSHOT"}},
                AcquisitionMode.BACKFILL,
            ),
            (
                {
                    "datasets": ["stocks"],
                    "windows": {"stocks": "2025-01-01/2025-03-31"},
                    "request_count": 96,
                },
                AcquisitionMode.BACKFILL,
            ),
            ({}, AcquisitionMode.QUALIFICATION),
        ],
        ids=[
            "count",
            "actions-snapshot",
            "tickers-window",
            "before-1998",
            "over-ceiling",
            "qualification-mode",
        ],
    )
    def test_slices_the_plan_refuses(
        self, overrides: dict[str, Any], mode: AcquisitionMode
    ) -> None:
        document = slice_document(**overrides)
        if mode is AcquisitionMode.QUALIFICATION:
            with pytest.raises(InputError):
                parse_slice(slice_document(acquisition_mode="QUALIFICATION"))
            return
        with pytest.raises(pplan.ProductionPlanError):
            pplan.compile_plan(parse_slice(document), acquisition_mode=mode)

    def test_no_slice_can_exceed_the_per_run_request_ceiling(self) -> None:
        covered = parse_slice(
            slice_document(
                datasets=["stocks"], windows={"stocks": "2025-01-01/2025-02-17"}, request_count=96
            )
        )
        plan = pplan.compile_plan(covered, acquisition_mode=AcquisitionMode.UPDATE)
        assert plan.request_count == 96 == pplan.MAX_REQUESTS_PER_RUN

    def test_the_plan_refuses_a_slice_ceiling_above_the_compiled_one(self) -> None:
        with pytest.raises(pplan.ProductionPlanError):
            pplan.compile_plan(
                parse_slice(slice_document(max_response_bytes=pplan.MAX_RESPONSE_BYTES + 1)),
                acquisition_mode=AcquisitionMode.BACKFILL,
            )


# ---------------------------------------------------------------------------
# The end-to-end scenario
# ---------------------------------------------------------------------------


class FakeSecrets:
    def __init__(self, *, failure: str | None = None) -> None:
        self.failure = failure
        self.calls = 0

    def get_secret_value(self, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        if self.failure is not None:
            raise FakeClientError(self.failure)
        return {"SecretString": SECRET_VALUE, "ARN": kwargs.get("SecretId")}


@dataclass
class FakeProvider:
    """Answers each request with queued bytes; records every request coordinate."""

    responses: list[bytes] = field(default_factory=list)
    fail_at: int | None = None
    calls: list[tuple[int, str, str, int]] = field(default_factory=list)
    revealed: list[str] = field(default_factory=list)

    def fetch(self, request: pplan.ProductionRequest, *, credential: SharadarCredential) -> bytes:
        self.calls.append((request.ordinal, request.dataset, request.window, request.page_offset))
        if self.fail_at is not None and len(self.calls) == self.fail_at:
            raise RuntimeError("synthetic provider failure 000000000000")
        self.revealed.append(credential.reveal())
        return self.responses[request.ordinal]


@dataclass
class FakeS3Put:
    """A ``put_object``-only fake with create-only semantics and injectable failures."""

    objects: dict[str, bytes] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    fail_on: dict[str, str] = field(default_factory=dict)
    fail_after_calls: int | None = None
    fail_code: str = "InternalError"

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        key = kwargs["Key"]
        self.calls.append(key)
        assert kwargs["IfNoneMatch"] == "*" and kwargs["ServerSideEncryption"] == "AES256"
        if self.fail_after_calls is not None and len(self.calls) > self.fail_after_calls:
            raise FakeClientError(self.fail_code)
        if key in self.fail_on:
            raise FakeClientError(self.fail_on[key])
        if key in self.objects:
            raise FakeClientError("PreconditionFailed")
        self.objects[key] = kwargs["Body"]
        return {
            "ETag": '"synthetic"',
            "ChecksumSHA256": kwargs["ChecksumSHA256"],
            "ChecksumType": "FULL_OBJECT",
        }


class Scenario:
    def __init__(self, *, responses: list[bytes] | None = None, release: bool = True) -> None:
        constants = constants_for(ACQ)
        self.ssm = FakeSsm()
        self.ssm.values[constants.binding_parameter] = encode(binding_document(ACQ))
        self.input_bytes = encode(acquisition_input_document())
        self.ssm.values[constants.input_parameter] = self.input_bytes
        if release:
            self.ssm.values[constants.release_parameter] = build_release_document(
                actor=ACQ,
                task_arn=TASK_ARN,
                task_definition_arn=revision_arn(ACQ),
                identity=RUN_ID,
                input_digest=input_digest(self.input_bytes),
                network_interface_id=INTERFACE_ID,
                subnet_id=SUBNET_ID,
                verified_at=NOW - timedelta(seconds=10),
            )
        self.clock = FakeClock()
        self.secrets = FakeSecrets()
        self.provider = FakeProvider(
            responses=responses
            if responses is not None
            else [f"synthetic-payload-{i}".encode() for i in range(6)]
        )
        self.s3 = FakeS3Put()
        self.registry: Any = LedgerSpentIdentities([])
        self.secret_id = SECRET_ID

    def bootstrap(self) -> RunnerAdapters:
        return RunnerAdapters(
            environment_names=lambda: ["PATH", "ECS_CONTAINER_METADATA_URI_V4"],
            parameters=SsmParameterAdapter(ssm=self.ssm),
            metadata=lambda: metadata_document(ACQ),
            caller_identity=lambda: caller_identity(task_identity_arn(ACQ)),
            now=self.clock.now,
            monotonic=self.clock.monotonic,
            sleep=self.clock.sleep,
        )

    def processing(self) -> pp.ProcessingAdapters:
        return pp.ProcessingAdapters(
            secrets=self.secrets,
            secret_id=self.secret_id,
            provider=self.provider,
            s3=self.s3,
            monotonic=self.clock.monotonic,
            sleeper=self.clock.sleep,
            clock=self.clock.now,
        )

    def run(self) -> pp.AcquisitionReport:
        return pp.run_production_acquisition(
            compiled=compiled_task(ACQ),
            bootstrap=self.bootstrap(),
            registry=self.registry,
            processing=self.processing(),
        )

    def data_plane_calls(self) -> tuple[int, int, int]:
        return self.secrets.calls, len(self.provider.calls), len(self.s3.calls)


def _assert_counts_match(scenario: Scenario, report: pp.AcquisitionReport) -> None:
    secrets, provider, s3 = scenario.data_plane_calls()
    assert report.counts.secret_retrievals == secrets
    assert report.counts.provider_requests == provider
    assert report.counts.s3_operations == s3
    rendered = repr(report) + repr(report.counts) + repr(report.bootstrap)
    for canary in CANARIES:
        assert canary not in rendered
    assert SECRET_VALUE not in rendered and BUCKET not in rendered


class TestEndToEnd:
    def test_one_bounded_acquisition_completes_with_a_complete_published_locator(self) -> None:
        scenario = Scenario()
        report = scenario.run()
        assert report.status is pp.AcquisitionStatus.COMPLETED
        assert report.bootstrap.outcome is RunnerOutcome.RELEASED
        assert report.completed_requests == report.planned_requests == 6
        assert report.payloads_written == 6 and report.payloads_already_present == 0
        assert (
            report.locator is not None
            and report.locator.status is LocatorPublicationStatus.PUBLISHED
        )
        # Exactly the plan's requests, in canonical order, once each.
        assert [c[0] for c in scenario.provider.calls] == [0, 1, 2, 3, 4, 5]
        # 3 conditional writes per request + 1 locator = 19; provider 6; secret 1.
        assert report.counts.provider_requests == 6 and report.counts.s3_operations == 19
        assert report.counts.secret_retrievals == 1
        _assert_counts_match(scenario, report)
        # Pacing at the compiled interval, on the injected clock, before every request.
        assert scenario.clock.sleeps.count(1.0) >= 5
        # The credential was revealed only inside the provider adapter.
        assert scenario.provider.revealed == [SECRET_VALUE] * 6

    def test_every_object_lies_in_a_production_namespace_and_nowhere_else(self) -> None:
        scenario = Scenario()
        scenario.run()
        keys = sorted(scenario.s3.objects)
        assert len(keys) == 19
        for key in keys:
            assert (
                key.startswith("bronze/sharadar/actions/production/")
                or key.startswith("bronze/sharadar/tickers/production/")
                or key.startswith("bronze/_production_claims/")
                or key == f"bronze/sharadar/_indexes/{RUN_ID}.json"
            ), key
        assert sum(1 for k in keys if "/production/objects/sha256/" in k) == 6
        assert sum(1 for k in keys if "/production/acquisitions/" in k) == 6
        assert sum(1 for k in keys if k.startswith("bronze/_production_claims/")) == 6
        # Nothing under any earlier namespace.
        assert not any("/objects/sha256/" in k and "/production/" not in k for k in keys)
        assert not any(k.startswith("bronze/_acquisition_claims/") for k in keys)
        assert not any("/qualification/" in k for k in keys)

    def test_the_published_locator_is_the_one_the_build_reader_admits(self) -> None:
        scenario = Scenario()
        scenario.run()
        locator_bytes = scenario.s3.objects[f"bronze/sharadar/_indexes/{RUN_ID}.json"]
        document = decode_run_locator(locator_bytes)
        assert (
            document["completeness"] == "COMPLETE"
            and document["publication_state_unknown"] is False
        )
        row = LedgerRow(
            run_identity=RUN_ID,
            slice=parse_slice(slice_document()),
            plan_digest=PLAN_DIGEST,
            outcome="COMPLETED",
            launched_at=NOW,
            completed_at=NOW + timedelta(hours=1),
        )
        validated = validate_run_locator(document, run_id=RUN_ID, ledger_row=row)
        assert len(validated.entries) == 6

        class GetOnly:
            def get_object(self, **kwargs: Any) -> Any:
                class Body:
                    def __init__(self, payload: bytes) -> None:
                        self._p, self._o = payload, 0

                    def read(self, size: int) -> bytes:
                        chunk = self._p[self._o : self._o + size]
                        self._o += len(chunk)
                        return chunk

                if kwargs["Key"] not in scenario.s3.objects:
                    raise FakeClientError("NoSuchKey")
                return {"Body": Body(scenario.s3.objects[kwargs["Key"]])}

        reader = ProductionLocatorReader(client=GetOnly(), licensed_bucket=BUCKET)
        read_back = reader.read_run_locator(run_id=RUN_ID, ledger_row=row)
        objects = list(reader.iter_locator_objects(read_back))
        assert [payload for _, payload, _ in objects] == scenario.provider.responses
        assert reader.get_object_count == 13

    def test_identical_payloads_across_distinct_requests_keep_distinct_provenance(self) -> None:
        same = b"synthetic-header-only-page"
        scenario = Scenario(responses=[same] * 6)
        report = scenario.run()
        assert report.status is pp.AcquisitionStatus.COMPLETED
        keys = sorted(scenario.s3.objects)
        payloads = [k for k in keys if "/objects/sha256/" in k]
        claims = [k for k in keys if k.startswith("bronze/_production_claims/")]
        records = [k for k in keys if "/acquisitions/" in k]
        # One content-addressed payload per dataset; six distinct claims; six distinct records.
        assert len(payloads) == 2 and len(claims) == 6 and len(records) == 6
        assert sorted(c.rsplit(".", 2)[1] for c in claims) == ["00", "01", "02", "03", "04", "05"]
        # Dispositions say exactly which writes created the payload and which found it present.
        assert report.payloads_written == 2 and report.payloads_already_present == 4
        locator = decode_run_locator(scenario.s3.objects[f"bronze/sharadar/_indexes/{RUN_ID}.json"])
        dispositions = [e["payload_disposition"] for e in locator["entries"]]
        assert dispositions == [
            "WRITTEN",
            "ALREADY_PRESENT",
            "WRITTEN",
            "ALREADY_PRESENT",
            "ALREADY_PRESENT",
            "ALREADY_PRESENT",
        ]
        # 6 claims + 6 payload attempts + 6 records + 1 locator, every attempt counted.
        assert report.counts.s3_operations == 19 == len(scenario.s3.calls)


class TestRefusalsBeforeAnyDataPlaneCall:
    @pytest.mark.parametrize(
        ("mutate", "defect"),
        [
            (
                lambda s: s.ssm.values.__setitem__(
                    constants_for(ACQ).input_parameter,
                    encode(acquisition_input_document(plan_digest=OTHER_PLAN_DIGEST)),
                ),
                "mismatched plan",
            ),
            (
                lambda s: s.ssm.values.__setitem__(
                    constants_for(ACQ).input_parameter,
                    encode(acquisition_input_document(slice=slice_document(request_count=5))),
                ),
                "unauthorized slice",
            ),
            (
                lambda s: s.ssm.values.__setitem__(
                    constants_for(ACQ).input_parameter,
                    encode(
                        acquisition_input_document(
                            slice=slice_document(
                                datasets=["stocks"],
                                windows={"stocks": "2025-01-01/2025-01-02"},
                                request_count=4,
                            )
                        )
                    ),
                ),
                "slice not authorized by digest",
            ),
            (lambda s: setattr(s, "registry", LedgerSpentIdentities([RUN_ID])), "spent identity"),
            (
                lambda s: setattr(s, "registry", UnavailableSpentIdentities()),
                "identity status unavailable",
            ),
            (lambda s: s.ssm.values.pop(constants_for(ACQ).input_parameter), "missing plan/input"),
        ],
        ids=[
            "mismatched-plan",
            "unauthorized-slice",
            "other-slice",
            "spent",
            "unavailable",
            "missing-input",
        ],
    )
    def test_input_refusals_make_zero_data_plane_calls(
        self, mutate: Callable[[Scenario], Any], defect: str
    ) -> None:
        scenario = Scenario()
        mutate(scenario)
        report = scenario.run()
        assert report.status is pp.AcquisitionStatus.REFUSED_BOOTSTRAP, defect
        assert report.bootstrap.outcome is RunnerOutcome.REFUSED_INPUT
        assert scenario.data_plane_calls() == (0, 0, 0)
        assert report.counts.data_plane_operations == 0 and report.locator is None
        _assert_counts_match(scenario, report)

    def test_the_input_contract_names_each_input_defect(self) -> None:
        from kalpamani.data.production.sharadar.inputs import decode_input, parse_acquisition_input

        admitted = parse_acquisition_input(
            decode_input(encode(acquisition_input_document(plan_digest=OTHER_PLAN_DIGEST))),
            now=NOW,
            registry=LedgerSpentIdentities([]),
        )
        with pytest.raises(InputError) as info:
            pplan.bind_plan(admitted)
        assert info.value.defect is InputDefect.PLAN_DIGEST_MISMATCH

    def test_barrier_refusal_makes_zero_data_plane_calls(self) -> None:
        scenario = Scenario(release=False)
        report = scenario.run()
        assert report.status is pp.AcquisitionStatus.REFUSED_BOOTSTRAP
        assert report.bootstrap.outcome is RunnerOutcome.REFUSED_NO_RELEASE
        assert scenario.data_plane_calls() == (0, 0, 0)
        assert report.bootstrap.barrier is not None and report.bootstrap.barrier.reads == 60

    def test_a_refused_credential_makes_no_provider_or_s3_call(self) -> None:
        scenario = Scenario()
        scenario.secrets = FakeSecrets(failure="AccessDeniedException")
        report = scenario.run()
        assert report.status is pp.AcquisitionStatus.REFUSED_CREDENTIAL
        assert report.halt is pp.ProcessingHalt.CREDENTIAL_REFUSED
        assert scenario.data_plane_calls() == (1, 0, 0) and report.locator is None
        _assert_counts_match(scenario, report)


class TestHalts:
    def _partial_locator(self, scenario: Scenario) -> dict[str, Any]:
        return decode_run_locator(scenario.s3.objects[f"bronze/sharadar/_indexes/{RUN_ID}.json"])

    def test_a_provider_failure_halts_keeps_completed_requests_and_publishes_a_partial_locator(
        self,
    ) -> None:
        scenario = Scenario()
        scenario.provider.fail_at = 3
        report = scenario.run()
        assert report.status is pp.AcquisitionStatus.HALTED
        assert report.halt is pp.ProcessingHalt.PROVIDER_FAILURE
        assert report.completed_requests == 2 and report.planned_requests == 6
        # The failed request was issued and counted; nothing after it was.
        assert report.counts.provider_requests == 3 == len(scenario.provider.calls)
        assert report.counts.s3_operations == 2 * 3 + 1
        locator = self._partial_locator(scenario)
        assert locator["completeness"] == "PARTIAL" and locator["completed_requests"] == 2
        assert (
            report.locator is not None
            and report.locator.status is LocatorPublicationStatus.PUBLISHED
        )
        with pytest.raises(RunLocatorError):
            validate_run_locator(
                locator,
                run_id=RUN_ID,
                ledger_row=LedgerRow(
                    run_identity=RUN_ID,
                    slice=parse_slice(slice_document()),
                    plan_digest=PLAN_DIGEST,
                    outcome="COMPLETED",
                    launched_at=NOW,
                    completed_at=NOW + timedelta(hours=1),
                ),
            )
        _assert_counts_match(scenario, report)
        assert "synthetic provider failure" not in repr(report)

    def test_the_request_budget_is_the_plans_and_is_never_exceeded(self) -> None:
        scenario = Scenario(responses=[b"x"] * 50)  # more answers available than the plan asks for
        report = scenario.run()
        assert report.status is pp.AcquisitionStatus.COMPLETED
        assert len(scenario.provider.calls) == 6 == report.planned_requests

    def test_a_response_over_the_ceiling_halts_before_any_write_for_it(self) -> None:
        scenario = Scenario()
        scenario.provider.responses[1] = b"x" * (4 * 1024 * 1024 + 1)
        report = scenario.run()
        assert report.status is pp.AcquisitionStatus.HALTED
        assert report.halt is pp.ProcessingHalt.RESPONSE_TOO_LARGE
        assert report.completed_requests == 1 and report.counts.s3_operations == 3 + 1

    def test_a_conditional_write_conflict_on_a_claim_halts_as_a_conflict(self) -> None:
        scenario = Scenario()
        first = scenario.run()
        assert first.status is pp.AcquisitionStatus.COMPLETED
        # A second run under the same (spent) identity, against the same store: the very
        # first claim name is occupied, and the run halts with nothing else written.
        second = Scenario()
        second.s3 = scenario.s3
        report = second.run()
        assert report.status is pp.AcquisitionStatus.HALTED
        assert report.halt is pp.ProcessingHalt.PUBLICATION_CONFLICT
        assert report.completed_requests == 0 and report.publication_state_unknown is False
        assert report.counts.s3_operations == 1 + 1  # the claim attempt, then the locator attempt
        assert (
            report.locator is not None
            and report.locator.status is LocatorPublicationStatus.NAME_OCCUPIED
        )

    def test_a_record_conflict_is_a_conflict_not_a_disposition(self) -> None:
        scenario = Scenario()
        scenario.run()
        record_key = next(
            k for k in scenario.s3.objects if "/acquisitions/" in k and k.endswith(".01.json")
        )
        fresh = Scenario()
        fresh.s3.objects[record_key] = b"occupant"
        report = fresh.run()
        assert (
            report.halt is pp.ProcessingHalt.PUBLICATION_CONFLICT and report.completed_requests == 1
        )

    @pytest.mark.parametrize(
        ("code", "halt", "unknown", "locator_attempts"),
        [
            ("AccessDenied", pp.ProcessingHalt.PUBLICATION_REFUSED, False, 1),
            ("InternalError", pp.ProcessingHalt.PUBLICATION_STATE_UNKNOWN, True, 3),
            ("ConditionalRequestConflict", pp.ProcessingHalt.PUBLICATION_STATE_UNKNOWN, True, 3),
            ("SomethingUnrecognised", pp.ProcessingHalt.PUBLICATION_STATE_UNKNOWN, True, 1),
        ],
    )
    def test_uncertain_publication_never_becomes_completion(
        self, code: str, halt: pp.ProcessingHalt, unknown: bool, locator_attempts: int
    ) -> None:
        scenario = Scenario()
        scenario.s3.fail_after_calls = 4  # the second request's payload write
        scenario.s3.fail_code = code
        report = scenario.run()
        assert report.status is pp.AcquisitionStatus.HALTED and report.halt is halt
        assert report.publication_state_unknown is unknown
        assert report.completed_requests == 1
        # No retry of the failed Bronze write and nothing after it. The PARTIAL locator
        # then follows the accepted locator policy: transient results may be retried
        # up to three attempts, definitive and unclassified ones never.
        assert report.locator is not None and report.locator.attempts == locator_attempts
        assert len(scenario.s3.calls) == 5 + locator_attempts
        _assert_counts_match(scenario, report)
        # Every later S3 call still fails, so the locator is never PUBLISHED.
        assert report.locator.status is not LocatorPublicationStatus.PUBLISHED

    def test_failure_before_locator_publication_reports_it_and_never_completes(self) -> None:
        scenario = Scenario()
        scenario.s3.fail_on[f"bronze/sharadar/_indexes/{RUN_ID}.json"] = "AccessDenied"
        report = scenario.run()
        assert report.status is pp.AcquisitionStatus.LOCATOR_NOT_PUBLISHED
        assert report.completed_requests == 6 and report.halt is None
        assert report.locator is not None and report.locator.attempts == 1
        assert report.counts.s3_operations == 19

    def test_locator_publication_uncertainty_is_reported_as_uncertainty(self) -> None:
        scenario = Scenario()
        scenario.s3.fail_on[f"bronze/sharadar/_indexes/{RUN_ID}.json"] = "SomethingUnrecognised"
        report = scenario.run()
        assert report.status is pp.AcquisitionStatus.LOCATOR_STATE_UNKNOWN
        assert report.locator is not None
        assert report.locator.status is LocatorPublicationStatus.STATE_UNKNOWN
        # An unclassified result is never retried (accepted locator policy).
        assert report.locator.attempts == 1 and report.counts.s3_operations == 19

    def test_a_transient_locator_failure_is_retried_within_the_accepted_budget(self) -> None:
        scenario = Scenario()
        scenario.s3.fail_on[f"bronze/sharadar/_indexes/{RUN_ID}.json"] = "InternalError"
        report = scenario.run()
        # Three attempts, all unresolved: the accepted policy reports NOT_PUBLISHED and
        # the run does not complete. Bronze writes were never retried.
        assert report.status is pp.AcquisitionStatus.LOCATOR_NOT_PUBLISHED
        assert report.locator is not None and report.locator.attempts == 3
        assert report.counts.s3_operations == 18 + 3 == len(scenario.s3.calls)

    def test_an_occupied_locator_name_is_reported_and_never_adopted(self) -> None:
        scenario = Scenario()
        scenario.s3.objects[f"bronze/sharadar/_indexes/{RUN_ID}.json"] = b"occupant"
        report = scenario.run()
        assert report.status is pp.AcquisitionStatus.LOCATOR_NAME_OCCUPIED
        assert scenario.s3.objects[f"bronze/sharadar/_indexes/{RUN_ID}.json"] == b"occupant"

    def test_the_deadline_halts_the_run_and_no_provider_request_starts_after_it(self) -> None:
        scenario = Scenario()
        original = scenario.provider.fetch

        def slow(request: pplan.ProductionRequest, *, credential: SharadarCredential) -> bytes:
            scenario.clock.seconds += 700.0
            return original(request, credential=credential)

        scenario.provider.fetch = slow  # type: ignore[method-assign]
        report = scenario.run()
        assert report.status is pp.AcquisitionStatus.HALTED
        assert report.halt is pp.ProcessingHalt.DEADLINE_EXHAUSTED
        assert report.completed_requests < 6
        assert report.counts.provider_requests == len(scenario.provider.calls)


class TestCompatibility:
    def test_the_qualification_and_general_bronze_builders_are_untouched(self) -> None:
        from datetime import UTC, datetime

        from kalpamani.data.ingest.bronze import RetrievalMetadata

        retrieval = RetrievalMetadata(
            provider="sharadar",
            dataset="actions",
            retrieved_at=datetime(2026, 9, 10, tzinfo=UTC),
            source_schema_version="synthetic-schema-v0",
            ingestion_run_id=RUN_ID,
            acquisition_mode=AcquisitionMode.QUALIFICATION,
            requested_range="1998-01-01/2026-09-09",
        )
        digest = "ab" * 32
        assert bronze_payload_key(retrieval=retrieval, payload=b"p").logical_key.startswith(
            "licensed/bronze/sharadar/actions/objects/sha256/"
        )
        assert bronze_acquisition_key(
            retrieval=retrieval, payload_digest=digest, record=b"{}"
        ).logical_key == (f"licensed/bronze/sharadar/actions/acquisitions/{digest}/{RUN_ID}.json")
        assert acquisition_claim_key(
            payload_digest=digest, run_id=RUN_ID, claim=b"{}"
        ).logical_key == (f"licensed/bronze/_acquisition_claims/{digest}/{RUN_ID}.json")
        assert qualification_payload_key(
            dataset="actions",
            execution_id="synthetic-exec-0001",
            request_ordinal=3,
            content_sha256=digest,
        ).logical_key == (
            f"licensed/bronze/sharadar/actions/qualification/synthetic-exec-0001/requests/03/sha256/{digest}"
        )

    def test_the_processing_module_imports_no_parser_no_sdk_and_no_read(self) -> None:
        import ast
        from pathlib import Path

        source = Path(pp.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert not any(m.startswith(("boto3", "botocore")) for m in imported)
        assert not any("parser" in m or "evaluator" in m for m in imported)
        body = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
        for forbidden in (
            ".get_object(",
            ".head_object(",
            ".list_objects",
            ".delete_object(",
            ".copy_object(",
        ):
            assert forbidden not in body

    def test_a_report_cannot_claim_completion_without_every_condition(self) -> None:
        from kalpamani.data.production.sharadar.outcomes import OperationCounts
        from kalpamani.data.production.sharadar.runner import RunnerReport, RunnerStage

        bootstrap = RunnerReport(
            outcome=RunnerOutcome.REFUSED_NO_RELEASE,
            stage=RunnerStage.RELEASE_BARRIER,
            counts=OperationCounts(),
            barrier=None,
        )
        with pytest.raises(ValueError, match="COMPLETED requires"):
            pp.AcquisitionReport(
                status=pp.AcquisitionStatus.COMPLETED,
                bootstrap=bootstrap,
                halt=None,
                completed_requests=5,
                planned_requests=6,
                payloads_written=5,
                payloads_already_present=0,
                publication_state_unknown=False,
                locator=None,
                counts=OperationCounts(),
            )

    def test_a_complete_locator_the_validator_refuses_is_downgraded_to_partial(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Belt and braces: if the document this run would publish as COMPLETE fails the
        accepted validator, it is published PARTIAL and the run does not report completion."""
        from kalpamani.data.production.sharadar.locator import RunLocatorDefect

        def refuse(*args: Any, **kwargs: Any) -> Any:
            raise RunLocatorError(RunLocatorDefect.FIELD_MALFORMED)

        monkeypatch.setattr(pp, "validate_run_locator", refuse)
        scenario = Scenario()
        report = scenario.run()
        assert report.status is pp.AcquisitionStatus.HALTED
        locator = decode_run_locator(scenario.s3.objects[f"bronze/sharadar/_indexes/{RUN_ID}.json"])
        assert locator["completeness"] == Completeness.PARTIAL.value
        assert PayloadDisposition.WRITTEN.value in {
            e["payload_disposition"] for e in locator["entries"]
        }
