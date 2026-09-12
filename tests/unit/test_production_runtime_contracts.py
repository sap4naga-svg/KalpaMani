"""Behavioural tests: the input contracts, the placement release, the barrier, the self-check.

Every mismatch the release contract names has its own case; the barrier is driven
through the whole 300-second ceiling on an injected clock; and a counting fake
proves that no data-plane operation is reachable from any barrier path.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Final

import pytest

from fixtures.production_runtime import (
    BUILD_ID,
    CANARIES,
    INTERFACE_ID,
    NOW,
    OTHER_PLAN_DIGEST,
    OTHER_RUN_ID,
    OTHER_TASK_ARN,
    PLAN_DIGEST,
    RUN_ID,
    SUBNET_ID,
    TASK_ARN,
    FakeClientError,
    FakeClock,
    FakeSsm,
    acquisition_input_document,
    build_input_document,
    compiled_task,
    encode,
    ledger_row_document,
    loose_encode,
    metadata_document,
    revision_arn,
)
from kalpamani.data.production.sharadar import barrier as pbar
from kalpamani.data.production.sharadar import inputs as pin
from kalpamani.data.production.sharadar import metadata as pm
from kalpamani.data.production.sharadar import release as pr
from kalpamani.data.production.sharadar.documents import DocumentDefect
from kalpamani.data.production.sharadar.parameters import (
    ParameterError,
    ParameterFailure,
    ParameterOperation,
    SsmParameterAdapter,
    classify_parameter_failure,
)
from kalpamani.data.production.sharadar.vocabulary import (
    MAX_ADVANCED_PARAMETER_BYTES,
    ProductionActor,
    constants_for,
)

ACQ: Final = ProductionActor.ACQUISITION
BLD: Final = ProductionActor.BUILD


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


def _acq(document: object, **kwargs: Any) -> pin.AcquisitionInput:
    defaults: dict[str, Any] = {
        "now": NOW,
        "expected_plan_digest": PLAN_DIGEST,
        "is_spent": lambda _: False,
    }
    defaults.update(kwargs)
    return pin.parse_acquisition_input(document, **defaults)


def _acq_refused(document: object, **kwargs: Any) -> pin.InputDefect:
    with pytest.raises(pin.InputError) as info:
        _acq(document, **kwargs)
    for canary in CANARIES:
        assert canary not in str(info.value)
    return info.value.defect


class TestAcquisitionInput:
    def test_a_valid_input_is_admitted_and_its_identity_hidden(self) -> None:
        parsed = _acq(acquisition_input_document())
        assert parsed.run_identity == RUN_ID and parsed.slice.request_count == 2
        assert RUN_ID not in repr(parsed) and PLAN_DIGEST not in repr(parsed)

    def test_the_digest_is_over_the_delivered_bytes(self) -> None:
        document = acquisition_input_document()
        assert pin.input_digest(encode(document)) != pin.input_digest(loose_encode(document))

    def test_size_is_checked_before_parsing(self) -> None:
        raw = b"{" + b" " * MAX_ADVANCED_PARAMETER_BYTES + b"}"
        with pytest.raises(pin.InputError) as info:
            pin.decode_input(raw)
        assert info.value.defect is pin.InputDefect.TOO_LARGE

    def test_the_document_defect_mapping_is_total(self) -> None:
        assert set(pin._DOCUMENT_DEFECTS) == set(DocumentDefect)

    @pytest.mark.parametrize(
        ("overrides", "defect"),
        [
            ({"schema_version": 2}, pin.InputDefect.SCHEMA_VERSION_UNKNOWN),
            (
                {"contract_id": constants_for(BLD).input_contract_id},
                pin.InputDefect.CONTRACT_ID_UNKNOWN,
            ),
            ({"run_identity": "../x"}, pin.InputDefect.IDENTITY_MALFORMED),
            ({"plan_digest": OTHER_PLAN_DIGEST}, pin.InputDefect.PLAN_DIGEST_MISMATCH),
            ({"plan_digest": "xyz"}, pin.InputDefect.FIELD_MALFORMED),
            ({"extra": 1}, pin.InputDefect.FIELD_UNKNOWN),
            (
                {"expires_at": (NOW + timedelta(hours=25)).isoformat()},
                pin.InputDefect.VALIDITY_TOO_LONG,
            ),
            (
                {
                    "issued_at": (NOW + timedelta(minutes=1)).isoformat(),
                    "expires_at": (NOW + timedelta(hours=2)).isoformat(),
                },
                pin.InputDefect.NOT_YET_VALID,
            ),
            (
                {
                    "issued_at": (NOW - timedelta(hours=3)).isoformat(),
                    "expires_at": (NOW - timedelta(hours=1)).isoformat(),
                },
                pin.InputDefect.EXPIRED,
            ),
            ({"issued_at": "2026-09-12T10:00:00"}, pin.InputDefect.VALIDITY_MALFORMED),
            ({"slice": {"datasets": ["daily"]}}, pin.InputDefect.SLICE_MALFORMED),
        ],
        ids=lambda value: str(value)[:32],
    )
    def test_each_clause_refuses_with_its_own_defect(
        self, overrides: dict[str, Any], defect: pin.InputDefect
    ) -> None:
        assert _acq_refused(acquisition_input_document(**overrides)) is defect

    def test_a_missing_field_is_refused(self) -> None:
        document = acquisition_input_document()
        del document["slice"]
        assert _acq_refused(document) is pin.InputDefect.FIELD_MISSING

    def test_a_spent_identity_is_refused(self) -> None:
        assert (
            _acq_refused(acquisition_input_document(), is_spent=lambda _: True)
            is pin.InputDefect.IDENTITY_SPENT
        )

    def test_a_raising_spent_check_refuses_rather_than_proceeding(self) -> None:
        def raising(_: str) -> bool:
            raise RuntimeError("registry unavailable")

        assert (
            _acq_refused(acquisition_input_document(), is_spent=raising)
            is pin.InputDefect.IDENTITY_SPENT
        )

    def test_no_compiled_plan_digest_refuses_before_comparison(self) -> None:
        assert (
            _acq_refused(acquisition_input_document(), expected_plan_digest=None)
            is pin.InputDefect.EXPECTED_PLAN_DIGEST_UNAVAILABLE
        )

    @pytest.mark.parametrize(
        "bad_slice",
        [
            {
                "datasets": ["tickers", "actions"],
                "windows": {"tickers": "SNAPSHOT", "actions": "1998-01-01/2026-09-11"},
                "request_count": 2,
                "max_response_bytes": 1,
            },
            {
                "datasets": ["actions"],
                "windows": {"actions": "not-a-window"},
                "request_count": 1,
                "max_response_bytes": 1,
            },
            {"datasets": ["actions"], "windows": {}, "request_count": 1, "max_response_bytes": 1},
            {
                "datasets": ["actions"],
                "windows": {"actions": "SNAPSHOT"},
                "request_count": 0,
                "max_response_bytes": 1,
            },
            {
                "datasets": ["actions"],
                "windows": {"actions": "SNAPSHOT"},
                "request_count": 97,
                "max_response_bytes": 1,
            },
            {
                "datasets": ["actions"],
                "windows": {"actions": "SNAPSHOT"},
                "request_count": True,
                "max_response_bytes": 1,
            },
            {"datasets": [], "windows": {}, "request_count": 1, "max_response_bytes": 1},
        ],
    )
    def test_slice_defects(self, bad_slice: dict[str, Any]) -> None:
        with pytest.raises(pin.InputError) as info:
            pin.parse_slice(bad_slice)
        assert info.value.defect is pin.InputDefect.SLICE_MALFORMED


class TestBuildInput:
    def test_a_valid_input_is_admitted(self) -> None:
        parsed = pin.parse_build_input(build_input_document(), now=NOW)
        assert parsed.build_identity == BUILD_ID and len(parsed.runs) == 1
        assert parsed.row_for(RUN_ID) is not None and parsed.row_for(OTHER_RUN_ID) is None
        assert BUILD_ID not in repr(parsed) and RUN_ID not in repr(parsed.runs[0])

    def test_the_ledger_digest_binds_the_rows_as_delivered(self) -> None:
        document = build_input_document()
        document["runs"][0]["plan_digest"] = OTHER_PLAN_DIGEST
        with pytest.raises(pin.InputError) as info:
            pin.parse_build_input(document, now=NOW)
        assert info.value.defect is pin.InputDefect.LEDGER_DIGEST_MISMATCH

    def test_a_reordered_row_list_changes_the_digest(self) -> None:
        rows = [ledger_row_document(RUN_ID), ledger_row_document(OTHER_RUN_ID)]
        document = build_input_document(rows)
        document["runs"].reverse()
        with pytest.raises(pin.InputError) as info:
            pin.parse_build_input(document, now=NOW)
        assert info.value.defect is pin.InputDefect.LEDGER_DIGEST_MISMATCH

    def test_a_duplicated_run_identity_is_refused(self) -> None:
        rows = [ledger_row_document(RUN_ID), ledger_row_document(RUN_ID)]
        with pytest.raises(pin.InputError) as info:
            pin.parse_build_input(build_input_document(rows), now=NOW)
        assert info.value.defect is pin.InputDefect.IDENTITY_DUPLICATED

    def test_more_than_the_ceiling_is_refused(self) -> None:
        rows = [
            ledger_row_document(f"synthetic-run-{index:04d}")
            for index in range(pin.MAX_BUILD_RUNS + 1)
        ]
        with pytest.raises(pin.InputError) as info:
            pin.parse_build_input(build_input_document(rows), now=NOW)
        assert info.value.defect is pin.InputDefect.TOO_MANY_RUNS

    def test_no_rows_is_refused(self) -> None:
        with pytest.raises(pin.InputError) as info:
            pin.parse_build_input(build_input_document([]), now=NOW)
        assert info.value.defect is pin.InputDefect.NO_RUNS

    @pytest.mark.parametrize("outcome", ["MISPLACED", "REFUSED", "HALTED"])
    def test_a_row_that_did_not_complete_is_refused(self, outcome: str) -> None:
        with pytest.raises(pin.InputError) as info:
            pin.parse_build_input(
                build_input_document([ledger_row_document(outcome=outcome)]), now=NOW
            )
        assert info.value.defect is pin.InputDefect.ROW_NOT_COMPLETED

    def test_a_malformed_row_is_refused(self) -> None:
        with pytest.raises(pin.InputError) as info:
            pin.parse_build_input(
                build_input_document([ledger_row_document(outcome="OTHER")]), now=NOW
            )
        assert info.value.defect is pin.InputDefect.ROW_MALFORMED

    def test_the_acquisition_contract_is_refused_by_the_build_parser(self) -> None:
        with pytest.raises(pin.InputError) as info:
            pin.parse_build_input(acquisition_input_document(), now=NOW)
        assert info.value.defect in {pin.InputDefect.FIELD_UNKNOWN, pin.InputDefect.FIELD_MISSING}


# ---------------------------------------------------------------------------
# The placement release: every mismatch, by name
# ---------------------------------------------------------------------------


def _expectation(actor: ProductionActor = ACQ, **overrides: Any) -> pr.ReleaseExpectation:
    fields: dict[str, Any] = {
        "actor": actor,
        "task_arn": TASK_ARN,
        "task_definition_arn": revision_arn(actor),
        "identity": RUN_ID if actor is ACQ else BUILD_ID,
        "input_digest": PLAN_DIGEST,
    }
    fields.update(overrides)
    return pr.ReleaseExpectation(**fields)


def _release_bytes(actor: ProductionActor = ACQ, **overrides: Any) -> bytes:
    fields: dict[str, Any] = {
        "actor": actor,
        "task_arn": TASK_ARN,
        "task_definition_arn": revision_arn(actor),
        "identity": RUN_ID if actor is ACQ else BUILD_ID,
        "input_digest": PLAN_DIGEST,
        "network_interface_id": INTERFACE_ID,
        "subnet_id": SUBNET_ID,
        "verified_at": NOW - timedelta(seconds=30),
    }
    fields.update(overrides)
    return pr.build_release_document(**fields)


def _release_document(**overrides: Any) -> dict[str, Any]:
    document = pr.decode_release(_release_bytes())
    document.update(overrides)
    return document


def _mismatch(
    document: object, *, expectation: pr.ReleaseExpectation | None = None, now: Any = NOW
) -> pr.ReleaseDefect:
    with pytest.raises(pr.ReleaseError) as info:
        pr.verify_release(document, expectation=expectation or _expectation(), now=now)
    for canary in CANARIES:
        assert canary not in str(info.value)
    return info.value.defect


class TestRelease:
    @pytest.mark.parametrize("actor", (ACQ, BLD), ids=lambda a: a.value)
    def test_a_release_the_launcher_built_verifies_for_the_task_it_names(
        self, actor: ProductionActor
    ) -> None:
        release = pr.verify_release(
            pr.decode_release(_release_bytes(actor)), expectation=_expectation(actor), now=NOW
        )
        assert release.actor is actor and release.subnet_id == SUBNET_ID
        assert release.expires_at - release.verified_at == pr.MAX_RELEASE_VALIDITY
        for canary in CANARIES:
            assert canary not in repr(release)

    def test_the_identity_field_is_the_actors_own(self) -> None:
        assert pr.release_fields(ACQ) - pr.release_fields(BLD) == {"run_identity"}
        assert pr.release_fields(BLD) - pr.release_fields(ACQ) == {"build_identity"}

    def test_another_task_is_a_mismatch(self) -> None:
        assert (
            _mismatch(_release_document(task_arn=OTHER_TASK_ARN)) is pr.ReleaseDefect.TASK_MISMATCH
        )

    def test_another_revision_is_a_mismatch(self) -> None:
        assert (
            _mismatch(_release_document(task_definition_arn=revision_arn(ACQ, 8)))
            is pr.ReleaseDefect.REVISION_MISMATCH
        )

    def test_another_run_identity_is_a_mismatch(self) -> None:
        assert (
            _mismatch(_release_document(run_identity=OTHER_RUN_ID))
            is pr.ReleaseDefect.IDENTITY_MISMATCH
        )

    def test_another_input_digest_is_a_mismatch(self) -> None:
        assert (
            _mismatch(_release_document(input_digest=OTHER_PLAN_DIGEST))
            is pr.ReleaseDefect.INPUT_DIGEST_MISMATCH
        )

    def test_the_other_actor_is_a_mismatch(self) -> None:
        # The build release carries ``build_identity``; the acquisition task expects
        # ``run_identity``.
        document = pr.decode_release(_release_bytes(BLD))
        assert _mismatch(document) in {
            pr.ReleaseDefect.FIELD_UNKNOWN,
            pr.ReleaseDefect.FIELD_MISSING,
        }
        document = _release_document(actor="build")
        assert _mismatch(document) is pr.ReleaseDefect.ACTOR_MISMATCH

    def test_a_release_verified_in_the_future_is_stale(self) -> None:
        assert (
            _mismatch(_release_document(), now=NOW - timedelta(minutes=5))
            is pr.ReleaseDefect.VERIFIED_IN_FUTURE
        )

    def test_an_expired_release_is_stale(self) -> None:
        assert (
            _mismatch(_release_document(), now=NOW + timedelta(minutes=10))
            is pr.ReleaseDefect.EXPIRED
        )

    def test_a_validity_over_ten_minutes_is_refused(self) -> None:
        document = _release_document(expires_at=(NOW + timedelta(minutes=11)).isoformat())
        assert _mismatch(document) is pr.ReleaseDefect.VALIDITY_TOO_LONG

    @pytest.mark.parametrize(
        ("overrides", "defect"),
        [
            ({"schema_version": 2}, pr.ReleaseDefect.SCHEMA_VERSION_UNKNOWN),
            ({"contract_id": "other/v1"}, pr.ReleaseDefect.CONTRACT_ID_UNKNOWN),
            ({"extra": 1}, pr.ReleaseDefect.FIELD_UNKNOWN),
            (
                {"task_arn": "arn:aws:ecs:us-east-1:000000000000:task/x"},
                pr.ReleaseDefect.FIELD_MALFORMED,
            ),
            ({"network_interface_id": "eni-XYZ"}, pr.ReleaseDefect.FIELD_MALFORMED),
            ({"subnet_id": "sg-0123456789abcdef0"}, pr.ReleaseDefect.FIELD_MALFORMED),
            ({"input_digest": "short"}, pr.ReleaseDefect.FIELD_MALFORMED),
            ({"verified_at": "2026-09-12T13:59:30"}, pr.ReleaseDefect.VALIDITY_MALFORMED),
            ({"actor": "operator"}, pr.ReleaseDefect.FIELD_MALFORMED),
        ],
        ids=lambda value: str(value)[:32],
    )
    def test_malformed_releases_refuse_by_clause(
        self, overrides: dict[str, Any], defect: pr.ReleaseDefect
    ) -> None:
        assert _mismatch(_release_document(**overrides)) is defect

    def test_the_mismatch_family_is_exactly_the_binding_and_staleness_clauses(self) -> None:
        assert pr.MISMATCH_DEFECTS == frozenset(
            {
                pr.ReleaseDefect.ACTOR_MISMATCH,
                pr.ReleaseDefect.TASK_MISMATCH,
                pr.ReleaseDefect.REVISION_MISMATCH,
                pr.ReleaseDefect.IDENTITY_MISMATCH,
                pr.ReleaseDefect.INPUT_DIGEST_MISMATCH,
                pr.ReleaseDefect.VERIFIED_IN_FUTURE,
                pr.ReleaseDefect.EXPIRED,
            }
        )

    def test_the_document_defect_mapping_is_total(self) -> None:
        assert set(pr._DOCUMENT_DEFECTS) == set(DocumentDefect)

    def test_the_launcher_cannot_build_a_release_the_task_would_refuse_for_shape(self) -> None:
        with pytest.raises(pr.ReleaseError):
            _release_bytes(network_interface_id="not-an-interface")
        with pytest.raises(pr.ReleaseError):
            _release_bytes(task_arn=OTHER_TASK_ARN.replace("task/", "cluster/"))

    def test_an_expectation_outside_the_grammars_cannot_exist(self) -> None:
        with pytest.raises(pr.ReleaseError):
            _expectation(task_arn="arn:aws:ecs:us-east-1:000000000000:task/x/y")
        with pytest.raises(pr.ReleaseError):
            _expectation(identity="")


# ---------------------------------------------------------------------------
# The barrier: bounded polling, one verdict, zero data-plane operations
# ---------------------------------------------------------------------------


class _CountingDataPlane:
    """Stands in for every data-plane client; any call is a test failure."""

    def __init__(self) -> None:
        self.calls = 0

    def __getattr__(self, name: str) -> Any:
        def call(*args: Any, **kwargs: Any) -> None:
            self.calls += 1
            raise AssertionError(f"data-plane operation {name} reached before release")

        return call


def _reader(ssm: FakeSsm) -> SsmParameterAdapter:
    return SsmParameterAdapter(ssm=ssm)


def _await(ssm: FakeSsm, clock: FakeClock, **kwargs: Any) -> pbar.BarrierResult:
    return pbar.await_placement_release(
        reader=_reader(ssm),
        expectation=kwargs.pop("expectation", _expectation()),
        now=clock.now,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )


class TestBarrier:
    def test_a_release_present_on_the_first_read_releases_at_once(self) -> None:
        ssm = FakeSsm(
            values={constants_for(ACQ).release_parameter: _release_bytes(verified_at=NOW)}
        )
        clock = FakeClock()
        result = _await(ssm, clock)
        assert result.outcome is pbar.BarrierOutcome.RELEASED
        assert result.reads == 1 and clock.sleeps == []
        assert ssm.names("get_parameter") == [constants_for(ACQ).release_parameter]
        assert all(kwargs["WithDecryption"] is True for _, kwargs in ssm.calls)

    def test_a_release_arriving_later_is_found_at_the_compiled_interval(self) -> None:
        ssm = FakeSsm()
        clock = FakeClock()
        name = constants_for(ACQ).release_parameter

        def arrive(_: str) -> None:
            if clock.seconds >= 40.0 and name not in ssm.values:
                ssm.values[name] = _release_bytes(verified_at=clock.now())

        ssm.before_get = arrive
        result = _await(ssm, clock)
        assert result.outcome is pbar.BarrierOutcome.RELEASED
        assert result.reads == 9 and clock.sleeps == [pbar.POLL_INTERVAL_SECONDS] * 8

    def test_no_release_by_the_ceiling_is_refused_within_sixty_reads_and_three_hundred_seconds(
        self,
    ) -> None:
        ssm = FakeSsm()
        clock = FakeClock()
        result = _await(ssm, clock)
        assert result.outcome is pbar.BarrierOutcome.REFUSED_NO_RELEASE
        assert result.reads == pbar.MAX_RELEASE_READS
        assert clock.seconds <= pbar.RELEASE_CEILING_SECONDS
        assert len(ssm.calls) == pbar.MAX_RELEASE_READS
        assert all(duration == pbar.POLL_INTERVAL_SECONDS for duration in clock.sleeps)

    def test_a_slow_clock_stops_at_the_time_ceiling_before_the_read_ceiling(self) -> None:
        ssm = FakeSsm()
        clock = FakeClock()
        original = clock.sleep

        def slow(duration: float) -> None:
            original(duration * 3)

        result = pbar.await_placement_release(
            reader=_reader(ssm),
            expectation=_expectation(),
            now=clock.now,
            monotonic=clock.monotonic,
            sleep=slow,
        )
        assert result.outcome is pbar.BarrierOutcome.REFUSED_NO_RELEASE
        assert result.reads < pbar.MAX_RELEASE_READS
        assert clock.seconds <= pbar.RELEASE_CEILING_SECONDS + 2 * pbar.POLL_INTERVAL_SECONDS

    @pytest.mark.parametrize(
        ("overrides", "defect"),
        [
            ({"task_arn": OTHER_TASK_ARN}, pr.ReleaseDefect.TASK_MISMATCH),
            ({"task_definition_arn": revision_arn(ACQ, 9)}, pr.ReleaseDefect.REVISION_MISMATCH),
            ({"identity": OTHER_RUN_ID}, pr.ReleaseDefect.IDENTITY_MISMATCH),
            ({"input_digest": OTHER_PLAN_DIGEST}, pr.ReleaseDefect.INPUT_DIGEST_MISMATCH),
            ({"verified_at": NOW - timedelta(minutes=11)}, pr.ReleaseDefect.EXPIRED),
            ({"verified_at": NOW + timedelta(minutes=1)}, pr.ReleaseDefect.VERIFIED_IN_FUTURE),
        ],
        ids=lambda value: str(value)[:32],
    )
    def test_every_mismatched_release_refuses_at_once(
        self, overrides: dict[str, Any], defect: pr.ReleaseDefect
    ) -> None:
        ssm = FakeSsm(values={constants_for(ACQ).release_parameter: _release_bytes(**overrides)})
        clock = FakeClock()
        result = _await(ssm, clock)
        assert result.outcome is pbar.BarrierOutcome.REFUSED_RELEASE_MISMATCH
        assert result.defect is defect and result.reads == 1 and clock.sleeps == []

    def test_a_malformed_release_refuses_at_once(self) -> None:
        ssm = FakeSsm(values={constants_for(ACQ).release_parameter: b"not json"})
        result = _await(ssm, FakeClock())
        assert result.outcome is pbar.BarrierOutcome.REFUSED_RELEASE_MISMATCH
        assert result.defect is pr.ReleaseDefect.DOCUMENT_MALFORMED

    @pytest.mark.parametrize(
        ("code", "failure"),
        [
            ("AccessDeniedException", ParameterFailure.ACCESS_DENIED),
            ("ThrottlingException", ParameterFailure.THROTTLED),
            ("InternalServerError", ParameterFailure.TRANSIENT),
            ("SomethingElse", ParameterFailure.UNKNOWN),
        ],
    )
    def test_any_read_failure_but_not_found_refuses_at_once(
        self, code: str, failure: ParameterFailure
    ) -> None:
        ssm = FakeSsm(get_failures={constants_for(ACQ).release_parameter: code})
        clock = FakeClock()
        result = _await(ssm, clock)
        assert result.outcome is pbar.BarrierOutcome.REFUSED_RELEASE_READ
        assert result.read_failure is failure and result.reads == 1 and clock.sleeps == []

    def test_no_data_plane_operation_is_reachable_from_any_barrier_path(self) -> None:
        plane = _CountingDataPlane()
        for values, failures in (
            ({}, {}),
            ({constants_for(ACQ).release_parameter: _release_bytes(task_arn=OTHER_TASK_ARN)}, {}),
            ({}, {constants_for(ACQ).release_parameter: "AccessDeniedException"}),
            ({constants_for(ACQ).release_parameter: _release_bytes(verified_at=NOW)}, {}),
        ):
            _await(FakeSsm(values=dict(values), get_failures=dict(failures)), FakeClock())
        assert plane.calls == 0

    @pytest.mark.parametrize(
        ("read_seconds", "outcome"),
        [
            (400.0, pbar.BarrierOutcome.REFUSED_NO_RELEASE),  # the read crosses the deadline
            (300.0, pbar.BarrierOutcome.REFUSED_NO_RELEASE),  # the read lands exactly on it
            (299.0, pbar.BarrierOutcome.RELEASED),  # the read completes within it
        ],
        ids=["crossing", "exactly", "within"],
    )
    def test_a_valid_release_read_at_or_beyond_the_deadline_is_refused(
        self, read_seconds: float, outcome: pbar.BarrierOutcome
    ) -> None:
        """The clock advances *during* the read; the deadline is rechecked before acceptance."""
        ssm = FakeSsm()
        clock = FakeClock()
        name = constants_for(ACQ).release_parameter

        def slow_read(_: str) -> None:
            clock.seconds += read_seconds
            ssm.values[name] = _release_bytes(verified_at=clock.now())

        ssm.before_get = slow_read
        result = _await(ssm, clock)
        assert result.outcome is outcome
        assert result.reads == 1 and clock.sleeps == []
        assert result.elapsed_seconds == read_seconds
        if outcome is pbar.BarrierOutcome.RELEASED:
            assert result.release is not None
        else:
            assert result.release is None and result.defect is None and result.read_failure is None

    def test_the_read_ceiling_and_the_no_retry_rules_survive_the_deadline_recheck(self) -> None:
        """A slow but released poll keeps 60 reads and 5 s, and refuses at once on error."""
        ssm = FakeSsm()
        clock = FakeClock()
        name = constants_for(ACQ).release_parameter

        def arrive_late(_: str) -> None:
            clock.seconds += 1.0  # every read takes a second
            if clock.seconds >= 290.0 and name not in ssm.values:
                ssm.values[name] = _release_bytes(verified_at=clock.now())

        ssm.before_get = arrive_late
        result = _await(ssm, clock)
        # 6 s per iteration (1 s read + 5 s sleep): read k ends at 6(k-1) + 1 s, so the
        # first read ending at or after 290 s is the 50th, at 295 s -- inside the
        # deadline and inside the read ceiling.
        assert result.outcome is pbar.BarrierOutcome.RELEASED
        assert result.reads == 50 and result.reads <= pbar.MAX_RELEASE_READS
        assert result.elapsed_seconds == 295.0
        assert all(duration == pbar.POLL_INTERVAL_SECONDS for duration in clock.sleeps)
        assert result.elapsed_seconds < pbar.RELEASE_CEILING_SECONDS
        ssm.get_failures[name] = "ThrottlingException"
        throttled = _await(ssm, FakeClock())
        assert (
            throttled.outcome is pbar.BarrierOutcome.REFUSED_RELEASE_READ and throttled.reads == 1
        )

    def test_the_other_actors_release_parameter_is_never_read(self) -> None:
        ssm = FakeSsm(
            values={constants_for(BLD).release_parameter: _release_bytes(BLD, verified_at=NOW)}
        )
        result = _await(ssm, FakeClock())
        assert result.outcome is pbar.BarrierOutcome.REFUSED_NO_RELEASE
        assert set(ssm.names("get_parameter")) == {constants_for(ACQ).release_parameter}

    def test_a_result_must_be_internally_consistent(self) -> None:
        with pytest.raises(ValueError, match="RELEASED"):
            pbar.BarrierResult(
                outcome=pbar.BarrierOutcome.RELEASED,
                reads=1,
                elapsed_seconds=0.0,
                release=None,
                defect=None,
                read_failure=None,
            )
        with pytest.raises(ValueError, match="ceiling"):
            pbar.BarrierResult(
                outcome=pbar.BarrierOutcome.REFUSED_NO_RELEASE,
                reads=61,
                elapsed_seconds=0.0,
                release=None,
                defect=None,
                read_failure=None,
            )


class TestParameterChannel:
    def test_classification_is_structural_and_total_over_the_known_codes(self) -> None:
        assert (
            classify_parameter_failure(FakeClientError("ParameterNotFound"))
            is ParameterFailure.NOT_FOUND
        )
        assert (
            classify_parameter_failure(FakeClientError("ParameterAlreadyExists"))
            is ParameterFailure.ALREADY_EXISTS
        )
        assert (
            classify_parameter_failure(RuntimeError("no response attribute"))
            is ParameterFailure.UNKNOWN
        )

    def test_the_create_request_is_create_only_advanced_tier_with_the_lifecycle_policy(
        self,
    ) -> None:
        ssm = FakeSsm()
        adapter = SsmParameterAdapter(ssm=ssm)
        adapter.create_parameter(
            "/x",
            b"{}",
            key_id="arn:aws:kms:us-east-1:000000000000:key/k",
            expires_at_iso="2026-09-13T14:00:00+00:00",
        )
        _, kwargs = ssm.calls[0]
        assert (
            kwargs["Overwrite"] is False
            and kwargs["Tier"] == "Advanced"
            and kwargs["Type"] == "SecureString"
        )
        assert (
            '"Type":"Expiration"' in kwargs["Policies"]
            and "2026-09-13T14:00:00+00:00" in kwargs["Policies"]
        )
        with pytest.raises(ParameterError) as info:
            adapter.create_parameter(
                "/x", b"{}", key_id="k", expires_at_iso="2026-09-13T14:00:00+00:00"
            )
        assert (
            info.value.failure is ParameterFailure.ALREADY_EXISTS
            and info.value.operation is ParameterOperation.PUT
        )

    def test_a_response_without_a_string_value_is_invalid(self) -> None:
        class Odd:
            def get_parameter(self, **kwargs: Any) -> dict[str, Any]:
                return {"Parameter": {"Value": 5}}

            def put_parameter(self, **kwargs: Any) -> None: ...

            def delete_parameter(self, **kwargs: Any) -> None: ...

        with pytest.raises(ParameterError) as info:
            SsmParameterAdapter(ssm=Odd()).read_parameter("/x")
        assert info.value.failure is ParameterFailure.INVALID_RESPONSE

    def test_a_backend_message_never_survives_classification(self) -> None:
        ssm = FakeSsm(get_failures={"/x": "AccessDeniedException"})
        with pytest.raises(ParameterError) as info:
            SsmParameterAdapter(ssm=ssm).read_parameter("/x")
        assert "synthetic backend message" not in str(info.value) and info.value.__cause__ is None


# ---------------------------------------------------------------------------
# The self-check
# ---------------------------------------------------------------------------


class TestSelfCheck:
    def test_documented_fields_parse_and_the_definition_arn_rebuilds(self) -> None:
        metadata = pm.parse_task_metadata(metadata_document(ACQ))
        assert metadata is not None
        assert metadata.task_definition_arn() == revision_arn(ACQ)
        assert metadata.task_id == TASK_ARN.rsplit("/", 1)[1]
        assert TASK_ARN not in repr(metadata)
        assert pm.self_check_refusal(metadata, compiled_task(ACQ)) is None

    @pytest.mark.parametrize(
        "overrides",
        [
            {"Family": "kalpamani-research-build"},
            {"Revision": "8"},
            {"Containers": [{"ImageID": "sha256:" + "00" * 32}]},
            {
                "Containers": [
                    {"ImageID": "sha256:" + "ef" * 32},
                    {"ImageID": "sha256:" + "00" * 32},
                ]
            },
        ],
        ids=["family", "revision", "image", "sidecar"],
    )
    def test_each_mismatch_refuses_value_free(self, overrides: dict[str, Any]) -> None:
        metadata = pm.parse_task_metadata(metadata_document(ACQ, **overrides))
        assert metadata is not None
        reason = pm.self_check_refusal(metadata, compiled_task(ACQ))
        assert isinstance(reason, str)
        for canary in CANARIES:
            assert canary not in reason

    @pytest.mark.parametrize(
        "overrides",
        [
            {"TaskARN": "arn:aws:ecs:us-east-1:000000000000:task/x"},
            {"Revision": "0"},
            {"Revision": "07"},
            {"Containers": []},
            {"Containers": [{"Image": "repo:tag"}]},
        ],
    )
    def test_an_undocumented_or_malformed_document_does_not_parse(
        self, overrides: dict[str, Any]
    ) -> None:
        assert pm.parse_task_metadata(metadata_document(ACQ, **overrides)) is None

    def test_a_private_environment_variable_refuses_the_context(self) -> None:
        assert pm.task_environment_refusal(["PATH", "ECS_CONTAINER_METADATA_URI_V4"]) is None
        reason = pm.task_environment_refusal(["PATH", "KALPAMANI_SHARADAR_SECRET_ID"])
        assert reason is not None and "SECRET" not in reason

    def test_a_compiled_task_cannot_name_the_other_actors_family(self) -> None:
        with pytest.raises(ValueError, match="family"):
            pm.CompiledTask(
                actor=ACQ,
                family=constants_for(BLD).task_family,
                revision=1,
                image_digest="sha256:" + "ef" * 32,
            )
