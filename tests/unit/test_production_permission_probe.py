"""The permission-probe mechanisms (ADR-0048), on fakes and synthetic records only.

The task-role subcells are exercised by a probe task; the launcher's ``ExecuteCommand``
refusal against its own held probe task; the probe input and observation contracts; the
receipt's permission block; the launch records' probe kind; the launcher's one check hook;
and the whole flow through the real permission tool -- prepare, authorize, launch, complete
from a hand-read receipt, clean up -- with counting fakes for every client. Nothing here is
AWS verification: **mocked results are not AWS verification.**
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import Any, Final

import pytest
from test_production_permission_cells import (
    DENIED,
    NO_CONTENT,
    NOT_FOUND,
    OK,
    _Tool,
    runner,
    tool,
)

from fixtures.production_entry import (
    ProbeHarness,
    permission_context,
)
from fixtures.production_launch import FakeClients, launch_inputs_document
from fixtures.production_runtime import (
    IMAGE_DIGEST,
    TASK_ARN,
    TASK_ID,
    FakeClientError,
    FakeEc2,
    FakeEcs,
    encode,
    interface_entry,
    probe_revision_arn,
    task_entry,
)
from kalpamani.data.contracts.canonical import canonical_bytes
from kalpamani.data.production.sharadar import launch_records as lr
from kalpamani.data.production.sharadar import permission_cells as pc
from kalpamani.data.production.sharadar import permission_probe as pp
from kalpamani.data.production.sharadar import r3_verification as r3
from kalpamani.data.production.sharadar import receipts as pr
from kalpamani.data.production.sharadar.compute import CompiledLaunch, run_task_request
from kalpamani.data.production.sharadar.entry import (
    EXIT_STATUS,
    PROBE_ENTRIES,
    PROBE_OUTCOMES,
    TaskEntry,
    TaskOutcome,
    TaskReceipt,
)
from kalpamani.data.production.sharadar.launcher import (
    HELD_READY_CEILING_SECONDS,
    HeldTask,
    LaunchAdapters,
    LaunchAuthorization,
    launch_authorized_run,
)
from kalpamani.data.production.sharadar.outcomes import (
    HeldCheckOutcome,
    LaunchOutcome,
    RunnerOutcome,
)
from kalpamani.data.production.sharadar.permission_client import (
    OPERATION_SERVICE,
    SdkPermissionClient,
    single_service_client,
)
from kalpamani.data.production.sharadar.vocabulary import ProductionActor

ACQ: Final = ProductionActor.ACQUISITION
BLD: Final = ProductionActor.BUILD
TIMEOUT: Final = r3.Observation(status=None, transport_failure="timeout")
SERVICE_DENIED: Final = r3.Observation(
    status=400, code="AccessDeniedException", message="synthetic"
)
INVALID_PARAMETER: Final = r3.Observation(
    status=400, code="InvalidParameterException", message="synthetic"
)
CANARIES: Final = ("synthetic-licensed-bucket", "synthetic/production/sharadar", TASK_ARN)
#: The probe task, discovered by the session tag and confirmed STOPPED.
LISTED_PROBE: Final = r3.Observation(status=200, task_arns=(TASK_ARN,))
#: The permission block a held probe's receipt carries: it issued nothing and held.
HELD_BLOCK: Final[dict[str, Any]] = {
    "observed": r3.ObservedClass.NOT_EXERCISED,
    "outcome": pp.SubcellOutcome.UNDECIDED,
    "operations": 0,
    "held_seconds": 180,
}
STOPPED: Final = r3.Observation(status=200, task_statuses=((TASK_ARN, "STOPPED"),))


# ---------------------------------------------------------------------------
# Classification: every service's denial, not S3's alone
# ---------------------------------------------------------------------------


def test_a_non_s3_denial_is_a_denial_and_an_unknown_answer_decides_nothing() -> None:
    assert pc.classify(SERVICE_DENIED) is r3.ObservedClass.DENIED_OTHER
    unauthorized = r3.Observation(status=403, code="UnauthorizedOperation", message="x")
    assert pc.classify(unauthorized) is r3.ObservedClass.DENIED_OTHER
    assert pc.classify(DENIED) is r3.ObservedClass.DENIED_OTHER
    assert pc.classify(INVALID_PARAMETER) is r3.ObservedClass.AMBIGUOUS
    assert pc.classify(TIMEOUT) is r3.ObservedClass.TIMEOUT
    assert pc.classify(OK) is r3.ObservedClass.OK_200
    # The accepted S3 classifier is unchanged: it does not know the service code.
    assert r3.classify(SERVICE_DENIED) is r3.ObservedClass.AMBIGUOUS
    cell = pc.subcell("R4-SECRET-GET-QUALIFICATION-HUMAN")
    assert pc.decide(cell, pc.classify(SERVICE_DENIED)) is pc.SubcellOutcome.MATCHED
    assert pc.decide(cell, pc.classify(INVALID_PARAMETER)) is pc.SubcellOutcome.UNDECIDED


# ---------------------------------------------------------------------------
# The probe input and observation contracts
# ---------------------------------------------------------------------------


class TestProbeContracts:
    def test_a_probe_input_round_trips_and_is_held_to_the_catalogue(self) -> None:
        context = permission_context()
        harness = ProbeHarness(subcell_id="R4-SECRET-GET-TASK", context=context)
        parsed = pp.parse_permission_probe_input(
            harness.input_bytes, now=harness.clock.now(), actor=ACQ
        )
        assert parsed == harness.probe_input and parsed.digest == harness.probe_input.digest
        assert not parsed.held and parsed.identity == "probe-" + harness.stamp
        rebuilt = pc.resolved_target_from(parsed.target)
        assert (
            rebuilt.digest
            == context.resolve(harness.cell, stamp=harness.stamp, prerequisites={}).digest
        )
        assert "PermissionProbeInput(" in repr(parsed) and "synthetic" not in repr(parsed)
        # The other actor's input is refused for this actor; without an actor it parses.
        with pytest.raises(ValueError):
            pp.parse_permission_probe_input(harness.input_bytes, now=harness.clock.now(), actor=BLD)
        assert pp.parse_permission_probe_input(harness.input_bytes, now=harness.clock.now())

    @pytest.mark.parametrize(
        ("subcell_id", "hold", "overrides", "detail"),
        [
            ("R4-SECRET-GET-TASK", 30, {}, "a task subcell never holds"),
            ("R6-ACQ-EXECUTE-COMMAND", 0, {}, "a held subcell holds"),
            ("R4-SECRET-GET-HUMAN", 0, {}, "a runtime subcell is not a probe's"),
            ("R8-GET", 0, {}, "a blocked subcell is not a probe's"),
            ("R6-BLD-RUN-OWN-REVISION", 0, {}, "an R-1-evidenced subcell is not a probe's"),
            ("R4-SECRET-GET-TASK", 0, {"identity": "probe-20260912T140000Z-ffff"}, "identity"),
            ("R4-SECRET-GET-TASK", 0, {"subcell_id": "R4-NOTHING"}, "unknown subcell"),
            ("R4-SECRET-GET-TASK", 0, {"actor": "build"}, "another actor"),
            ("R4-SECRET-GET-TASK", 0, {"statement_sha256": "zz"}, "digest"),
            ("R4-SECRET-GET-TASK", 0, {"hold_seconds": pp.PROBE_HOLD_CEILING_SECONDS + 1}, "hold"),
            ("R4-SECRET-GET-TASK", 0, {"extra": 1}, "closed field set"),
            (
                "R4-SECRET-GET-TASK",
                0,
                {"contract_id": "kalpamani-permission-probe-input/v0"},
                "contract",
            ),
        ],
    )
    def test_a_malformed_or_mismatched_probe_input_is_refused(
        self, subcell_id: str, hold: int, overrides: dict[str, Any], detail: str
    ) -> None:
        context = permission_context()
        if subcell_id in ("R4-SECRET-GET-HUMAN", "R8-GET", "R6-BLD-RUN-OWN-REVISION"):
            # Not a probe subcell: the harness cannot even resolve a probe target for it
            # under the catalogue's rules, so the document is built by hand.
            base = ProbeHarness(subcell_id="R4-SECRET-GET-TASK", context=context)
            document = base.probe_input.document()
            document["subcell_id"] = subcell_id
            document["target"]["kind"] = pc.subcell(subcell_id).target.value
            raw = encode(document)
            now = base.clock.now()
        else:
            harness = ProbeHarness(
                subcell_id=subcell_id,
                context=context,
                hold_seconds=hold,
                input_overrides=overrides,
            )
            raw = harness.input_bytes
            now = harness.clock.now()
        with pytest.raises(ValueError):
            pp.parse_permission_probe_input(raw, now=now)

    def test_the_target_kind_the_validity_window_and_the_size_are_held(self) -> None:
        context = permission_context()
        harness = ProbeHarness(subcell_id="R4-PUT-PAYLOAD-TASK", context=context)
        now = harness.clock.now()
        wrong_kind = harness.probe_input.document()
        wrong_kind["target"]["kind"] = pc.TargetKind.SILVER_OBJECT.value
        with pytest.raises(ValueError):
            pp.parse_permission_probe_input(encode(wrong_kind), now=now)
        expired = harness.probe_input.document()
        expired["expires_at"] = (now - timedelta(seconds=1)).isoformat()
        with pytest.raises(ValueError):
            pp.parse_permission_probe_input(encode(expired), now=now)
        too_long = harness.probe_input.document()
        too_long["expires_at"] = (now + timedelta(hours=25)).isoformat()
        with pytest.raises(ValueError):
            pp.parse_permission_probe_input(encode(too_long), now=now)
        with pytest.raises(ValueError):
            pp.parse_permission_probe_input(b"{" + b" " * pp.MAX_PROBE_INPUT_BYTES + b"}", now=now)
        with pytest.raises(ValueError):
            pp.parse_permission_probe_input(b"not json", now=now)

    def test_an_observation_round_trips_and_refuses_contradiction(self) -> None:
        observation = pp.PermissionProbeObservation(
            subcell_id="R4-SECRET-GET-TASK",
            statement_sha256="a1" * 32,
            attempt_sha256="b2" * 32,
            stamp="20260912T140000Z-abcd",
            observed=r3.ObservedClass.OK_200,
            outcome=pp.SubcellOutcome.MATCHED,
            created=False,
            possibly_created=False,
            operations=1,
            held_seconds=0,
        )
        assert pp.parse_permission_probe_observation(observation.document()) == observation
        with pytest.raises(ValueError):
            replace(observation, created=True, possibly_created=True)

        bad = observation.document()
        bad["observed"] = "SOMETHING"
        with pytest.raises(ValueError):
            pp.parse_permission_probe_observation(bad)
        bad = observation.document()
        del bad["held_seconds"]
        with pytest.raises(ValueError):
            pp.parse_permission_probe_observation(bad)
        assert "synthetic" not in repr(observation)


# ---------------------------------------------------------------------------
# The probe entry, through the real entry on fakes
# ---------------------------------------------------------------------------


def _expectation(harness: ProbeHarness) -> pr.ReceiptExpectation:
    from kalpamani.data.production.sharadar.inputs import input_digest

    return pr.ReceiptExpectation(
        entry=harness.entry,
        task_id=TASK_ID,
        task_definition_arn=probe_revision_arn(harness.actor),
        image_digest=IMAGE_DIGEST,
        configuration_digest=harness.compiled.configuration_digest,
        code_commit=harness.compiled.code_commit,
        identity=harness.identity,
        input_digest=input_digest(harness.input_bytes),
    )


class TestProbeEntry:
    def test_a_matched_probe_issues_exactly_one_operation_over_the_one_service(self) -> None:
        harness = ProbeHarness(subcell_id="R4-SECRET-GET-TASK", context=permission_context())
        harness.operation.answers = [OK]
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.PROBE_MATCHED and receipt.exit_code == 41
        assert receipt.runner is RunnerOutcome.RELEASED and receipt.evidence is not None
        assert receipt.permission is not None
        block = receipt.permission
        assert (
            block.subcell_id == "R4-SECRET-GET-TASK" and block.outcome is pp.SubcellOutcome.MATCHED
        )
        assert block.observed is r3.ObservedClass.OK_200 and block.operations == 1
        assert block.statement_sha256 == "a1" * 32 and block.attempt_sha256 == "b2" * 32
        assert block.stamp == harness.stamp and not block.created and block.held_seconds == 0
        # One client, for the one service, built after the barrier; one call, the secret's
        # exact name; the bootstrap's data-plane count stays zero.
        assert harness.services == [pc.Operation.SECRET_GET]
        assert [name for name, _ in harness.operation.calls] == ["get_secret_value"]
        assert harness.operation.calls[0][1]["args"] == ("synthetic/production/sharadar",)
        assert receipt.counts.data_plane_operations == 0 and harness.cleanups == 1
        rendered = "\n".join(receipt.render())
        assert "permission_subcell=R4-SECRET-GET-TASK" in rendered
        assert "permission_observed=OK_200 permission_outcome=MATCHED" in rendered
        for canary in CANARIES:
            assert canary not in rendered
        # The receipt line verifies against the launch record's expectation (v3).
        verified = pr.collect_and_verify(receipt.render(), expectation=_expectation(harness))
        assert verified.permission == block and verified.released
        assert verified.ledger_outcome == "PROBED"

    def test_an_inverted_and_an_undecided_answer_carry_their_class(self) -> None:
        harness = ProbeHarness(subcell_id="R4-PUT-PAYLOAD-TASK", context=permission_context())
        harness.operation.answers = [SERVICE_DENIED]
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.PROBE_INVERTED and receipt.exit_code == 42
        assert receipt.permission is not None
        assert receipt.permission.outcome is pp.SubcellOutcome.INVERTED
        assert receipt.permission.observed is r3.ObservedClass.DENIED_OTHER
        assert harness.services == [pc.Operation.S3_PUT_CONDITIONAL]
        call = harness.operation.calls[0]
        assert call[0] == "put_object" and call[1]["if_none_match"] is True
        assert call[1]["args"][2] == pc.SYNTHETIC_MARKER
        # A refused DENIED write created nothing; an open answer is possibly created.
        assert not receipt.permission.created and not receipt.permission.possibly_created
        harness = ProbeHarness(subcell_id="R4-PUT-PAYLOAD-TASK", context=permission_context())
        harness.operation.answers = [TIMEOUT]
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.PROBE_UNDECIDED and receipt.exit_code == 43
        assert receipt.permission is not None and receipt.permission.possibly_created
        assert receipt.permission.observed is r3.ObservedClass.TIMEOUT
        # A matched write records the created object (as a flag, never a key).
        harness = ProbeHarness(subcell_id="R4-PUT-PAYLOAD-TASK", context=permission_context())
        harness.operation.answers = [OK]
        receipt = harness.run()
        assert receipt.permission is not None and receipt.permission.created
        assert "objects/sha256" not in "\n".join(receipt.render())

    def test_a_held_probe_issues_nothing_and_holds_on_the_monotonic_clock(self) -> None:
        harness = ProbeHarness(
            subcell_id="R6-ACQ-EXECUTE-COMMAND", context=permission_context(), hold_seconds=30
        )
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.PROBE_HELD and receipt.exit_code == 44
        assert receipt.permission is not None
        assert receipt.permission.operations == 0 and receipt.permission.held_seconds == 30
        assert receipt.permission.outcome is pp.SubcellOutcome.UNDECIDED
        assert receipt.permission.observed is r3.ObservedClass.NOT_EXERCISED
        assert harness.services == [] and harness.operation.calls == []
        assert harness.clock.sleeps and sum(harness.clock.sleeps) == 30
        assert all(s <= pp.PROBE_HOLD_POLL_SECONDS for s in harness.clock.sleeps)
        verified = pr.collect_and_verify(receipt.render(), expectation=_expectation(harness))
        assert verified.permission == receipt.permission

    def test_a_probe_refuses_before_any_operation_client_on_the_accepted_paths(self) -> None:
        # No release: the barrier refuses; nothing issued, no permission block.
        harness = ProbeHarness(
            subcell_id="R4-SECRET-GET-TASK", context=permission_context(), release=False
        )
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.REFUSED_NO_RELEASE and receipt.permission is None
        assert harness.services == [] and receipt.runner is RunnerOutcome.REFUSED_NO_RELEASE
        verified = pr.collect_and_verify(receipt.render(), expectation=_expectation(harness))
        assert verified.permission is None and not verified.released
        # The other actor's input: the bootstrap refuses the input before any client.
        wrong = ProbeHarness(
            subcell_id="R4-SECRET-GET-TASK",
            context=permission_context(),
            input_overrides={"actor": "build"},
        )
        receipt = wrong.run()
        assert receipt.outcome is TaskOutcome.REFUSED_INPUT and wrong.services == []
        # A workstation credential variable: refused before the working directory exists.
        harness = ProbeHarness(subcell_id="R4-SECRET-GET-TASK", context=permission_context())
        harness.environment_names = (*harness.environment_names, "AWS_PROFILE")
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.REFUSED_CREDENTIAL_ENVIRONMENT
        assert harness.constructions.built == [] and harness.services == []
        # A configuration carrying an origin set is not a probe's.
        harness = ProbeHarness(subcell_id="R4-SECRET-GET-TASK", context=permission_context())
        with pytest.raises(ValueError):
            harness.configuration(origin_addresses=frozenset({"192.0.2.10"}))
        # The operation client refusing to build: a dependency refusal after the barrier.
        harness = ProbeHarness(subcell_id="R4-SECRET-GET-TASK", context=permission_context())

        def refuse(_operation: pc.Operation) -> Any:
            raise RuntimeError("no client")

        receipt = harness.run(operation_client=refuse)
        assert receipt.outcome is TaskOutcome.REFUSED_DEPENDENCY and receipt.permission is None
        assert receipt.runner is RunnerOutcome.RELEASED
        # A wrong factory type: a configuration refusal; a non-probe entry: a value error.
        from kalpamani.data.production.sharadar.entry import run_task_entry
        from kalpamani.data.production.sharadar.permission_probe_entry import (
            run_permission_probe_entry,
        )

        receipt = run_task_entry(
            entry=harness.entry,
            configuration=harness.configuration(),
            factories=object(),  # type: ignore[arg-type]
        )
        assert receipt.outcome is TaskOutcome.REFUSED_CONFIGURATION
        with pytest.raises(ValueError):
            run_permission_probe_entry(
                entry=TaskEntry.ACQUISITION,
                configuration=harness.configuration(),
                factories=harness.factories(),
            )

    def test_the_receipt_invariants_hold_the_permission_block_to_the_outcome(self) -> None:
        harness = ProbeHarness(subcell_id="R4-SECRET-GET-TASK", context=permission_context())
        harness.operation.answers = [OK]
        receipt = harness.run()
        assert receipt.permission is not None
        with pytest.raises(ValueError):
            replace(receipt, permission=None)
        with pytest.raises(ValueError):
            replace(receipt, outcome=TaskOutcome.PROBE_INVERTED)
        with pytest.raises(ValueError):
            replace(receipt, outcome=TaskOutcome.COMPLETED, permission=None)
        with pytest.raises(ValueError):
            replace(receipt, outcome=TaskOutcome.VERIFIED_BOOTSTRAP, permission=None)
        with pytest.raises(ValueError):
            replace(receipt, entry=TaskEntry.ACQUISITION_VERIFY)
        # Only a probe entry reaches a probe outcome, and every probe exit is closed.
        assert all(EXIT_STATUS[o] in (41, 42, 43, 44) for o in PROBE_OUTCOMES)
        assert PROBE_ENTRIES == {TaskEntry.ACQUISITION_PROBE, TaskEntry.BUILD_PROBE}

    def test_the_verifier_refuses_a_permission_block_that_contradicts_its_receipt(self) -> None:
        harness = ProbeHarness(subcell_id="R4-SECRET-GET-TASK", context=permission_context())
        harness.operation.answers = [OK]
        receipt = harness.run()
        line = pr.collect_receipt_line(receipt.render())
        document = pr.decode_receipt_line(line)
        expectation = _expectation(harness)

        def resigned(mutate: Any) -> dict[str, Any]:
            copy: dict[str, Any] = json.loads(json.dumps(document))
            mutate(copy)
            del copy["receipt_digest"]
            from kalpamani.data.contracts.canonical import sha256_hex

            copy["receipt_digest"] = sha256_hex(canonical_bytes(copy))
            return copy

        assert pr.verify_receipt(document, expectation=expectation).permission is not None
        for mutate, defect in (
            (
                lambda d: d.__setitem__("permission", None),
                pr.ReceiptDefect.EVIDENCE_CONTRADICTS_OUTCOME,
            ),
            (
                lambda d: d["permission"].__setitem__("outcome", "INVERTED"),
                pr.ReceiptDefect.EVIDENCE_CONTRADICTS_OUTCOME,
            ),
            (
                lambda d: d["permission"].__setitem__("held_seconds", 5),
                pr.ReceiptDefect.EVIDENCE_CONTRADICTS_OUTCOME,
            ),
            (
                lambda d: d["permission"].__setitem__("operations", -1),
                pr.ReceiptDefect.FIELD_MALFORMED,
            ),
            (lambda d: d.__setitem__("schema_version", 2), pr.ReceiptDefect.SCHEMA_VERSION_UNKNOWN),
            (
                lambda d: d.__setitem__("outcome", "VERIFIED_BOOTSTRAP"),
                pr.ReceiptDefect.EXIT_CODE_CONTRADICTS_OUTCOME,
            ),
        ):
            with pytest.raises(pr.ReceiptError) as raised:
                pr.verify_receipt(resigned(mutate), expectation=expectation)
            assert raised.value.defect is defect, defect
        # A verification receipt with a permission block, or a probe block on a verify entry.
        with pytest.raises(pr.ReceiptError):
            pr.verify_receipt(
                resigned(lambda d: d.update(entry=TaskEntry.ACQUISITION_VERIFY.value)),
                expectation=expectation,
            )


# ---------------------------------------------------------------------------
# The SDK client: the one service, and the documented requests
# ---------------------------------------------------------------------------


class TestSdkClient:
    def test_a_single_service_client_reaches_the_one_service_and_no_other(self) -> None:
        built: list[str] = []

        class Secrets:
            def get_secret_value(self, **kwargs: Any) -> dict[str, Any]:
                assert kwargs == {"SecretId": "s"}
                return {"ResponseMetadata": {"HTTPStatusCode": 200}, "SecretString": "never-read"}

        def client_for(service: str) -> Any:
            built.append(service)
            return Secrets()

        client = single_service_client(pc.Operation.SECRET_GET, client_for)
        observation = client.get_secret_value("s")
        assert pc.classify(observation) is r3.ObservedClass.OK_200 and built == ["secretsmanager"]
        assert observation.message is None  # the value is never read into the observation
        # Another service is refused before a client exists: an exception, never a permission.
        other = client.get_object("b", "k")
        assert pc.classify(other) is r3.ObservedClass.AMBIGUOUS and built == ["secretsmanager"]
        assert OPERATION_SERVICE[pc.Operation.ECS_EXECUTE_COMMAND] == "ecs"
        assert all(op in OPERATION_SERVICE for op in pc.Operation)

    def test_execute_command_sends_the_documented_interactive_request(self) -> None:
        calls: list[dict[str, Any]] = []

        class Ecs:
            def execute_command(self, **kwargs: Any) -> dict[str, Any]:
                calls.append(kwargs)
                raise FakeClientError("AccessDeniedException")

        client = SdkPermissionClient(lambda _s: Ecs())
        observation = client.execute_command(cluster_arn="c", task_arn="t")
        assert calls == [{"cluster": "c", "task": "t", "command": "/bin/true", "interactive": True}]
        # A FakeClientError is not botocore's ClientError: the shared client classifies
        # an unknown exception as an exception, and the boto3 adapter test holds the real
        # ClientError path at the intercepted transport.
        assert pc.classify(observation) in (
            r3.ObservedClass.AMBIGUOUS,
            r3.ObservedClass.DENIED_OTHER,
        )


# ---------------------------------------------------------------------------
# The launch records and the launcher's one check
# ---------------------------------------------------------------------------


class TestLaunchSide:
    def test_the_probe_kind_its_identity_and_the_registration(self) -> None:
        assert lr.identity_kind("probe-20260912T140000Z-abcd") is lr.LaunchKind.PERMISSION_PROBE
        assert lr.identity_kind("verify-x") is lr.LaunchKind.VERIFICATION
        inputs = lr.parse_launch_inputs(encode(launch_inputs_document(probe=True)))
        assert (ACQ, lr.LaunchKind.PERMISSION_PROBE) in inputs.targets
        compiled, target = lr.compile_launch(inputs, actor=ACQ, kind=lr.LaunchKind.PERMISSION_PROBE)
        assert compiled.probe and not compiled.verification and target.family.endswith("-probe")
        # A registration without the probe target is still a registration; it names none.
        older = lr.parse_launch_inputs(encode(launch_inputs_document()))
        assert (ACQ, lr.LaunchKind.PERMISSION_PROBE) not in older.targets
        with pytest.raises(lr.LaunchRecordError):
            lr.compile_launch(older, actor=ACQ, kind=lr.LaunchKind.PERMISSION_PROBE)
        # A probe target under the wrong family, or the other actor's role, is refused.
        document = launch_inputs_document(probe=True)
        document["actors"]["acquisition"]["permission_probe"] = document["actors"]["build"][
            "permission_probe"
        ]
        with pytest.raises(lr.LaunchRecordError):
            lr.parse_launch_inputs(encode(document))
        # Provisional ledger outcomes: a probe exit on a probe launch is PROBED; on any
        # other kind HALTED; a refusal is REFUSED.
        probe = lr.LaunchKind.PERMISSION_PROBE
        for code in (41, 42, 43, 44):
            assert (
                lr.provisional_ledger_outcome(
                    kind=probe, task_started=True, misplaced=False, exit_codes=(code,)
                )
                == "PROBED"
            )
        assert (
            lr.provisional_ledger_outcome(
                kind=lr.LaunchKind.VERIFICATION,
                task_started=True,
                misplaced=False,
                exit_codes=(41,),
            )
            == "HALTED"
        )
        assert (
            lr.provisional_ledger_outcome(
                kind=probe, task_started=True, misplaced=False, exit_codes=(18,)
            )
            == "HALTED"
        )
        assert (
            lr.provisional_ledger_outcome(
                kind=probe, task_started=True, misplaced=False, exit_codes=(15,)
            )
            == "REFUSED"
        )

    def test_a_probe_launch_carries_the_session_tag_and_nothing_else_does(self) -> None:
        from fixtures.production_runtime import compiled_launch

        plain = compiled_launch(ACQ)
        assert plain.started_by is None and "startedBy" not in run_task_request(plain)
        with pytest.raises(ValueError):
            compiled_launch(ACQ, started_by="kalpamani-permission-20260912T140000Z-abcd")
        probe = compiled_launch(
            ACQ,
            task_definition_arn=probe_revision_arn(ACQ),
            started_by="kalpamani-permission-20260912T140000Z-abcd",
        )
        assert probe.probe and run_task_request(probe)["startedBy"] == probe.started_by
        assert "overrides" not in run_task_request(probe)
        untagged = compiled_launch(ACQ, task_definition_arn=probe_revision_arn(ACQ))
        assert untagged.probe and "startedBy" not in run_task_request(untagged)
        with pytest.raises(ValueError):
            compiled_launch(ACQ, task_definition_arn=probe_revision_arn(ACQ), started_by="x")

    def test_the_while_running_check_is_a_released_probe_launch_s_alone(self) -> None:
        from fixtures.production_runtime import FakeClock, FakeSsm, compiled_launch

        def sequence(
            compiled: CompiledLaunch, identity: str, **kwargs: Any
        ) -> tuple[Any, list[str]]:
            def entry(status: str, **kw: Any) -> dict[str, Any]:
                document = task_entry(ACQ, status=status, **kw)
                document["taskDefinitionArn"] = compiled.task_definition_arn
                return document

            ecs = FakeEcs(
                run_response={
                    "tasks": [
                        entry(
                            "PROVISIONING",
                            attachment_status="PRECREATED",
                            interface_id=None,
                            subnet_id=None,
                        )
                    ],
                    "failures": [],
                },
                descriptions=[entry("PENDING"), entry("RUNNING"), entry("STOPPED", exit_code=44)],
            )
            adapters = LaunchAdapters(
                ecs=__import__(
                    "kalpamani.data.production.sharadar.compute", fromlist=["EcsTaskAdapter"]
                ).EcsTaskAdapter(ecs=ecs, compiled=compiled),
                ec2=__import__(
                    "kalpamani.data.production.sharadar.compute", fromlist=["Ec2InterfaceAdapter"]
                ).Ec2InterfaceAdapter(
                    ec2=FakeEc2(interface=interface_entry(public_ip="203.0.113.10"))
                ),
                human_parameters=__import__(
                    "kalpamani.data.production.sharadar.parameters",
                    fromlist=["SsmParameterAdapter"],
                ).SsmParameterAdapter(ssm=FakeSsm()),
                launcher_parameters=__import__(
                    "kalpamani.data.production.sharadar.parameters",
                    fromlist=["SsmParameterAdapter"],
                ).SsmParameterAdapter(ssm=FakeSsm()),
            )
            seen: list[str] = []
            clock = FakeClock()

            def check(held: HeldTask) -> None:
                seen.append(held.task_arn)
                assert held.last_status == "RUNNING" and held.describe_calls == 1
                assert held.task_definition_arn == compiled.task_definition_arn
                raise RuntimeError("the check's own failure never escapes")

            report = launch_authorized_run(
                compiled=compiled,
                adapters=adapters,
                authorization=LaunchAuthorization(identity=identity, input_bytes=b"{}"),
                identity_proof=lambda _path: None,
                now=clock.now,
                monotonic=clock.monotonic,
                sleep=clock.sleep,
                while_running=check,
                **kwargs,
            )
            return report, seen

        probe = compiled_launch(
            ACQ,
            task_definition_arn=probe_revision_arn(ACQ),
            started_by="kalpamani-permission-20260912T140000Z-abcd",
        )
        report, seen = sequence(probe, "probe-20260912T140000Z-abcd")
        assert report.outcome is LaunchOutcome.TASK_TERMINAL and seen == [TASK_ARN]
        assert report.observed_exit_code == 44 and report.task_started
        assert report.held_check is HeldCheckOutcome.INVOKED
        assert report.held_task is not None and report.held_task.last_status == "RUNNING"
        assert "arn:aws" not in repr(report.held_task)
        # Not a probe launch, or a probe identity on a plain launch: refused before anything.
        with pytest.raises(ValueError):
            sequence(compiled_launch(ACQ), "run-x")
        with pytest.raises(ValueError):
            sequence(probe, "verify-x")
        with pytest.raises(ValueError):
            sequence(
                compiled_launch(ACQ, task_definition_arn=probe_revision_arn(ACQ)),
                "probe-20260912T140000Z-abcd",
            )


# ---------------------------------------------------------------------------
# The whole flow through the real tool: prepare, authorize, launch, complete, clean up
# ---------------------------------------------------------------------------


class _ProbeTool(_Tool):
    """The permission tool over a registration that carries the probe targets, with the
    launch tool's fake clients for the probe launch."""

    def __init__(
        self, tmp_path: Path, actor: ProductionActor = ACQ, *, scenario: Any = None
    ) -> None:
        principal = pc.Principal.ACQUISITION_HUMAN if actor is ACQ else pc.Principal.BUILD_HUMAN
        super().__init__(tmp_path, principal)
        if scenario is not None:
            # Adopt another harness's scenario: its ledger, records and private root.
            from fixtures.production_runtime import binding_document
            from kalpamani.data.production.sharadar.vocabulary import constants_for
            from kalpamani.data.qualify.sharadar import runtime_binding as rb

            self.scenario, self.root = scenario, scenario.root
            self.client.records_dir = scenario.records
            self.env[rb.ENVIRONMENT_BINDING_ENV_VAR] = str(scenario.root / "environment.json")
            for name, binding_actor in (("acq", ACQ), ("bld", BLD)):
                (self.root / f"binding-{name}.json").write_bytes(
                    encode(binding_document(binding_actor))
                )
                self.env[constants_for(binding_actor).binding_env_var] = str(
                    self.root / f"binding-{name}.json"
                )
        document = json.loads(self.scenario.inputs.read_bytes())
        probe = launch_inputs_document(probe=True)["actors"]
        for name in document["actors"]:
            document["actors"][name]["permission_probe"] = probe[name]["permission_probe"]
        self.scenario.inputs.write_bytes(encode(document))
        self.actor = actor
        self.ecs = FakeEcs(
            run_response={
                "tasks": [
                    self._task(
                        status="PROVISIONING",
                        attachment_status="PRECREATED",
                        interface_id=None,
                        subnet_id=None,
                    )
                ],
                "failures": [],
            },
            descriptions=self.descriptions(41),
        )
        self.ec2 = FakeEc2(
            interface=interface_entry(public_ip="203.0.113.10" if actor is ACQ else None)
        )
        self.launch_clients = FakeClients(actor=actor, ecs_fake=self.ecs, ec2_fake=self.ec2)
        self.launch_clock = self.clock

    def _task(self, **kwargs: Any) -> dict[str, Any]:
        entry = task_entry(self.actor, **kwargs)
        entry["taskDefinitionArn"] = probe_revision_arn(self.actor)
        return entry

    def descriptions(self, exit_code: int | None, **last: Any) -> list[dict[str, Any]]:
        """PENDING, RUNNING, then the terminal description (or ``last`` overrides)."""
        terminal = (
            self._task(status="STOPPED", exit_code=exit_code) if not last else self._task(**last)
        )
        return [self._task(status="PENDING"), self._task(status="RUNNING"), terminal]

    def fields(self, **overrides: Any) -> dict[str, Any]:
        fields = super().fields()
        fields.update(
            {
                "launch_clients": self.launch_clients,
                "monotonic": self.clock.monotonic,
                "sleep": self.clock.sleep,
            }
        )
        fields.update(overrides)
        return fields

    def probe_input(self) -> pp.PermissionProbeInput:
        """The probe input the launch materialized, parsed under its contract."""
        raw = self.launch_clients.human_ssm.calls
        put = next(kw for name, kw in raw if name == "put_parameter")
        return pp.parse_permission_probe_input(put["Value"].encode("utf-8"), now=self.clock.now())

    def receipt_lines(self, task_outcome: TaskOutcome, **block: Any) -> Path:
        """The hand-read receipt of the probe task this tool launched, as a file."""
        from kalpamani.data.production.sharadar.inputs import input_digest
        from kalpamani.data.production.sharadar.outcomes import OperationCounts
        from kalpamani.data.production.sharadar.runner import BootstrapEvidence

        probe_input = self.probe_input()
        registered = json.loads(self.scenario.inputs.read_bytes())["actors"][self.actor.value][
            "permission_probe"
        ]
        entry = TaskEntry.ACQUISITION_PROBE if self.actor is ACQ else TaskEntry.BUILD_PROBE
        put = next(
            kw for name, kw in self.launch_clients.human_ssm.calls if name == "put_parameter"
        )
        fields_: dict[str, Any] = {
            "subcell_id": probe_input.subcell_id,
            "statement_sha256": probe_input.statement_sha256,
            "attempt_sha256": probe_input.attempt_sha256,
            "stamp": probe_input.stamp,
            "observed": r3.ObservedClass.OK_200,
            "outcome": pp.SubcellOutcome.MATCHED,
            "created": False,
            "possibly_created": False,
            "operations": 1,
            "held_seconds": 0,
        }
        fields_.update(block)
        released = task_outcome in PROBE_OUTCOMES
        receipt = TaskReceipt(
            entry=entry,
            outcome=task_outcome,
            runner=RunnerOutcome.RELEASED if released else RunnerOutcome.REFUSED_INPUT,
            counts=OperationCounts(parameter_reads=3, identity_calls=1),
            counts_observed=True,
            cleanup_failures=(),
            code_commit=registered["code_commit"],
            configuration_digest=registered["configuration_digest"],
            evidence=BootstrapEvidence(
                task_id=TASK_ID,
                task_definition_arn=probe_revision_arn(self.actor),
                image_digest=IMAGE_DIGEST,
                identity=probe_input.identity,
                input_digest=input_digest(put["Value"].encode("utf-8")),
            )
            if released
            else None,
            permission=pp.PermissionProbeObservation(**fields_) if released else None,
        )
        self.receipts = getattr(self, "receipts", 0) + 1
        path = self.root / f"receipt-{self.receipts}-{task_outcome.value}.txt"
        path.write_text("\n".join(receipt.render()) + "\n", encoding="utf-8")
        return path

    def control(self, tmp_path: Path) -> _Tool:
        """The control principal's tool, on this tool's clock (the launch advanced it)."""
        control = super().control(tmp_path)
        control.clock = self.clock
        return control

    def complete(self, subcell: str, receipt: Path, **overrides: Any) -> int:
        return self.main(
            "--complete-subcell",
            subcell,
            *self.base(),
            "--receipt-lines",
            str(receipt),
            **overrides,
        )

    def state(self, subcell: str) -> pc.SubcellState:
        evidence = self.evidence()
        return pc.derive_subcell(pc.subcell(subcell), evidence, r1_passed={ACQ: False, BLD: False})

    def status(self, subcell: str) -> pc.SubcellStatus:
        return self.state(subcell).status


def test_a_task_subcell_is_launched_completed_from_its_receipt_and_cleaned_up(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    t = _ProbeTool(tmp_path)
    subcell = "R4-SECRET-GET-TASK"
    statement = t.prepare(subcell)
    assert t.files("permission-statement") and t.status(subcell) is pc.SubcellStatus.UNEXECUTED
    authorization = t.authorize(subcell, statement)
    code = t.main(*t.execute_argv(subcell, authorization))
    out = capsys.readouterr().out
    assert code == tool.EXIT_PROBE_LAUNCHED, out
    assert tool.SENTENCES["probe_launched"] in out and "task_started=yes" in out
    assert "observed_exit_code=41" in out
    for canary in (*CANARIES, "arn:aws:ecs", "objects/sha256"):
        assert canary not in out
    # The attempt, the launch record, the evidence and the ledger row exist; no permission
    # record yet; the authorization is consumed; no workstation client was built.
    assert len(t.files("permission-attempt")) == 1 and t.files("permission-record") == []
    assert len(t.files("launch-record")) == 1 and len(t.files("launch-evidence")) == 1
    assert t.constructions == []
    ledger = t.scenario.store().read_ledger()[0]
    row = ledger.rows[-1]
    assert row.kind is lr.LaunchKind.PERMISSION_PROBE and row.outcome == "PROBED"
    assert row.evidence is lr.LedgerEvidence.EXIT_CODE_ONLY and row.identity.startswith("probe-")
    assert t.status(subcell) is pc.SubcellStatus.AWAITING_RECEIPT
    # The reservation beside the ledger attributes the launch to the attempt before
    # RunTask; the launch record names its specification and binds to it.
    reservation = t.scenario.store().reservation(row.identity)
    assert reservation is not None and reservation.kind is lr.LaunchKind.PERMISSION_PROBE
    launch = lr.parse_launch_record(t.files("launch-record")[0].read_bytes())
    assert launch.specification_digest == reservation.specification_digest
    from kalpamani.data.production.sharadar.launch_store import RecordBinding, bind_record

    assert bind_record(reservation, launch) is RecordBinding.BOUND
    probe_launch = t.evidence().probe_launches[reservation.specification.workload["attempt_sha256"]]
    assert probe_launch.record is not None and probe_launch.duplicates == 0
    # The RunTask request: the probe revision, the session tag, no override, no exec.
    run = t.ecs.names("run_task")[0]
    assert run["taskDefinition"] == probe_revision_arn(ACQ) and "overrides" not in run
    assert run["startedBy"] == pc.started_by_of(t.probe_input().stamp)
    assert run["enableExecuteCommand"] is False and run["count"] == 1
    # The probe input names the subcell, the statement, the attempt, the stamp, the target.
    probe_input = t.probe_input()
    attempt = pc.parse_permission_attempt(t.files("permission-attempt")[0].read_bytes())
    assert probe_input.subcell_id == subcell and probe_input.statement_sha256 == statement
    assert probe_input.attempt_sha256 == attempt.digest and probe_input.stamp == attempt.stamp
    assert (
        pc.resolved_target_from(probe_input.target).digest
        == pc.parse_permission_statement(
            t.files("permission-statement")[0].read_bytes()
        ).target_sha256
    )
    assert not probe_input.held
    # A second execution under the same authorization: consumed.
    assert (
        t.main(*t.execute_argv(subcell, authorization)) == tool.EXIT_REFUSED_AUTHORIZATION_CONSUMED
    )
    capsys.readouterr()
    # Completion from the hand-read receipt: the record, bound and identity-verified.
    receipt = t.receipt_lines(TaskOutcome.PROBE_MATCHED)
    assert t.complete(subcell, receipt) == tool.EXIT_COMPLETED
    out = capsys.readouterr().out
    assert tool.SENTENCES["completed"] in out and "outcome=MATCHED" in out
    records = t.files("permission-record")
    assert len(records) == 1
    record = pc.parse_permission_record(records[0].read_bytes())
    assert record.outcome is pc.SubcellOutcome.MATCHED and record.identity_verified
    assert record.attempt_sha256 == attempt.digest and record.started_task_ids == (TASK_ID,)
    assert record.started_by == pc.started_by_of(attempt.stamp) and record.operations == 1
    assert record.principal is pc.Principal.ACQUISITION_TASK
    row = t.scenario.store().read_ledger()[0].rows[-1]
    assert row.evidence is lr.LedgerEvidence.RECEIPT_VERIFIED and row.outcome == "PROBED"
    # The receipt is kept as evidence bound to the launch record by digest.
    evidence_files = t.files("probe-receipt")
    assert len(evidence_files) == 1
    kept = pc.parse_probe_receipt_evidence(evidence_files[0].read_bytes())
    assert kept.attempt_sha256 == attempt.digest and kept.identity == row.identity
    assert kept.launch_record_sha256 == pc.launch_record_digest(launch)
    # The probe task is a started task the cleanup must confirm STOPPED: unresolved
    # until a verified cleanup pass discovers it by the tag and describes it.
    assert t.status(subcell) is pc.SubcellStatus.CLEANUP_UNRESOLVED
    control = t.control(tmp_path)
    control.client.by_operation = {
        "list_tasks": [LISTED_PROBE],
        "describe_tasks": [STOPPED],
    }
    assert t.cleanup(control, []) == tool.EXIT_EXECUTED
    capsys.readouterr()
    assert t.status(subcell) is pc.SubcellStatus.PASSED
    # Completing twice changes nothing and says so; another receipt for the completed
    # attempt, an unlaunched subcell and a runtime subcell refuse.
    assert t.complete(subcell, receipt) == tool.EXIT_COMPLETION_RECORDED
    assert tool.SENTENCES["completion_recorded"] in capsys.readouterr().out
    assert len(t.files("permission-record")) == 1 and len(t.files("probe-receipt")) == 1
    other = t.receipt_lines(TaskOutcome.PROBE_MATCHED, operations=2)
    assert t.complete(subcell, other) == tool.EXIT_REFUSED_COMPLETION
    assert t.complete("R4-PUT-PAYLOAD-TASK", receipt) == tool.EXIT_REFUSED_COMPLETION
    assert t.complete("R4-SECRET-GET-HUMAN", receipt) == tool.EXIT_REFUSED_SUBCELL


def test_completion_refuses_a_receipt_that_does_not_belong_to_the_launch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    t = _ProbeTool(tmp_path)
    subcell = "R4-PUT-PAYLOAD-TASK"
    authorization = t.authorize(subcell, t.prepare(subcell))
    assert t.main(*t.execute_argv(subcell, authorization)) == tool.EXIT_PROBE_LAUNCHED
    capsys.readouterr()
    good = t.receipt_lines(TaskOutcome.PROBE_MATCHED, created=True)
    for name, block in (
        ("subcell", {"subcell_id": "R4-PUT-RECORD-TASK"}),
        ("statement", {"statement_sha256": "77" * 32}),
        ("attempt", {"attempt_sha256": "88" * 32}),
        ("stamp", {"stamp": "20260912T000000Z-0000"}),
    ):
        bad = t.receipt_lines(TaskOutcome.PROBE_MATCHED, created=True, **block)
        assert t.complete(subcell, bad) == tool.EXIT_REFUSED_COMPLETION, name
        assert t.files("permission-record") == []
    # A receipt whose binding digest names another task or another input is refused by
    # the accepted validator; a v2 receipt is not this contract.
    text = good.read_text(encoding="utf-8")
    line = pr.collect_receipt_line(text.splitlines())
    document = pr.decode_receipt_line(line)
    document["binding_digest"] = "99" * 32
    del document["receipt_digest"]
    from kalpamani.data.contracts.canonical import sha256_hex

    document["receipt_digest"] = sha256_hex(canonical_bytes(document))
    forged = t.root / "forged.txt"
    forged.write_text(pr.RECEIPT_LINE_PREFIX + canonical_bytes(document).decode("utf-8") + "\n")
    assert t.complete(subcell, forged) == tool.EXIT_REFUSED_COMPLETION
    empty = t.root / "empty.txt"
    empty.write_text("no receipt here\n", encoding="utf-8")
    assert t.complete(subcell, empty) == tool.EXIT_REFUSED_COMPLETION
    assert t.complete(subcell, t.root / "missing.txt") == tool.EXIT_REFUSED_COMPLETION
    # The good receipt completes: the created object is the attempt's exact key, and
    # the cleanup settles it and the probe task; nothing is created by the receipt alone.
    assert t.complete(subcell, good) == tool.EXIT_COMPLETED
    record = pc.parse_permission_record(t.files("permission-record")[0].read_bytes())
    attempt = pc.parse_permission_attempt(t.files("permission-attempt")[0].read_bytes())
    assert record.created_key == attempt.key and record.created_bucket == attempt.bucket
    assert t.status(subcell) is pc.SubcellStatus.CLEANUP_UNRESOLVED
    control = t.control(tmp_path)
    control.client.by_operation = {
        "delete_object": [NO_CONTENT],
        "head_object": [NOT_FOUND],
        "list_tasks": [LISTED_PROBE],
        "describe_tasks": [STOPPED],
    }
    assert t.cleanup(control, []) == tool.EXIT_EXECUTED
    assert t.status(subcell) is pc.SubcellStatus.PASSED


def test_a_probe_that_refused_before_its_operation_completes_as_undecided(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    t = _ProbeTool(tmp_path)
    t.ecs.descriptions = t.descriptions(12)
    subcell = "R4-SECRET-GET-TASK"
    authorization = t.authorize(subcell, t.prepare(subcell))
    assert t.main(*t.execute_argv(subcell, authorization)) == tool.EXIT_PROBE_LAUNCHED
    assert "observed_exit_code=12" in capsys.readouterr().out
    row = t.scenario.store().read_ledger()[0].rows[-1]
    assert row.outcome == "REFUSED" and row.kind is lr.LaunchKind.PERMISSION_PROBE
    refused = t.receipt_lines(TaskOutcome.REFUSED_INPUT)
    assert t.complete(subcell, refused) == tool.EXIT_COMPLETED
    out = capsys.readouterr().out
    assert "observed=NOT_EXERCISED outcome=UNDECIDED" in out
    record = pc.parse_permission_record(t.files("permission-record")[0].read_bytes())
    assert not record.identity_verified and record.operations == 0
    # UNDECIDED, never PASSED, never re-executed automatically; the probe task is still a
    # launched task the cleanup confirms.
    assert t.status(subcell) is pc.SubcellStatus.UNDECIDED
    control = t.control(tmp_path)
    control.client.by_operation = {
        "list_tasks": [LISTED_PROBE],
        "describe_tasks": [STOPPED],
    }
    assert t.cleanup(control, []) == tool.EXIT_EXECUTED
    assert t.status(subcell) is pc.SubcellStatus.UNDECIDED


def test_a_launch_that_starts_no_task_consumes_the_authorization_and_interrupts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    t = _ProbeTool(tmp_path)
    subcell = "R4-SECRET-GET-TASK"
    authorization = t.authorize(subcell, t.prepare(subcell))
    # A stale input parameter: the sequence refuses before RunTask.
    from kalpamani.data.production.sharadar.vocabulary import constants_for

    t.launch_clients.human_ssm.values[constants_for(ACQ).input_parameter] = b"stale"
    code = t.main(*t.execute_argv(subcell, authorization))
    out = capsys.readouterr().out
    assert code == tool.EXIT_PROBE_NOT_STARTED and tool.SENTENCES["probe_not_started"] in out
    assert t.ecs.names("run_task") == [] and t.files("launch-record") == []
    row = t.scenario.store().read_ledger()[0].rows[-1]
    assert row.outcome == "REFUSED" and row.kind is lr.LaunchKind.PERMISSION_PROBE
    assert t.status(subcell) is pc.SubcellStatus.INTERRUPTED
    assert (
        t.main(*t.execute_argv(subcell, authorization)) == tool.EXIT_REFUSED_AUTHORIZATION_CONSUMED
    )
    capsys.readouterr()
    # A misplaced task: stopped by the launcher, no release, no check; the attempt stays
    # interrupted and the cleanup discovers the task by the tag.
    t2 = _ProbeTool(tmp_path / "two")
    t2.ecs.descriptions = [t2._task(status="RUNNING", subnet_id="subnet-0ffffffffffffffff")] * 2
    authorization = t2.authorize(subcell, t2.prepare(subcell))
    code = t2.main(*t2.execute_argv(subcell, authorization))
    out = capsys.readouterr().out
    assert code == tool.EXIT_PROBE_LAUNCHED and "launch=MISPLACED" in out
    assert t2.ecs.names("stop_task") and t2.status(subcell) is pc.SubcellStatus.AWAITING_RECEIPT
    control = t2.control(tmp_path / "two")
    control.client.by_operation = {
        "list_tasks": [LISTED_PROBE],
        "describe_tasks": [STOPPED],
    }
    assert t2.cleanup(control, []) == tool.EXIT_EXECUTED


def test_the_launcher_s_execute_command_refusal_runs_against_its_own_held_probe(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    t = _ProbeTool(tmp_path)
    t.ecs.descriptions = t.descriptions(44)
    subcell = "R6-ACQ-EXECUTE-COMMAND"
    statement = t.prepare(subcell)
    prepared = pc.parse_permission_statement(t.files("permission-statement")[0].read_bytes())
    assert prepared.target is pc.TargetKind.OWN_TASK
    authorization = t.authorize(subcell, statement)
    t.client.by_operation = {"execute_command": [SERVICE_DENIED]}
    code = t.main(*t.execute_argv(subcell, authorization))
    out = capsys.readouterr().out
    assert code == tool.EXIT_EXECUTED, out
    assert "outcome=MATCHED" in out and "tasks_started=1" in out
    # The check was made while the task ran, against exactly the launched task, under the
    # launcher's profile, with the documented request; the record was written at once.
    call = t.client.calls[-1]
    assert call[0] == "execute_command"
    assert call[1] == {"cluster_arn": t.context().inputs.cluster_arn, "task_arn": TASK_ARN}
    assert t.constructions == [
        (pc.PRINCIPAL_PROFILE[pc.Principal.ACQUISITION_LAUNCHER], "us-east-1")
    ]
    record = pc.parse_permission_record(t.files("permission-record")[0].read_bytes())
    assert record.outcome is pc.SubcellOutcome.MATCHED and record.identity_verified
    assert record.started_task_ids == (TASK_ID,) and record.stop_acknowledged_ids == ()
    assert t.probe_input().held and t.probe_input().hold_seconds == tool.PROBE_HOLD_SECONDS
    # The precondition: a fresh RUNNING description of exactly the launched task, on the
    # registered revision and image, before the check -- kept as evidence.
    held = pc.parse_held_task_evidence(t.files("held-task")[0].read_bytes())
    assert held.check is HeldCheckOutcome.INVOKED and held.last_status == "RUNNING"
    assert held.task_id == TASK_ID and held.task_definition_arn == probe_revision_arn(ACQ)
    assert held.image_digest == IMAGE_DIGEST and held.describe_calls == 1
    assert [c[0] for c in t.ecs.calls].count("describe_tasks") == 3  # placement, ready, terminal
    # The check's record awaits the probe's own receipt: a held, released probe.
    assert t.status(subcell) is pc.SubcellStatus.AWAITING_RECEIPT
    held_receipt = t.receipt_lines(TaskOutcome.PROBE_HELD, **HELD_BLOCK)
    assert t.complete(subcell, held_receipt) == tool.EXIT_COMPLETED
    assert len(t.files("permission-record")) == 1 and len(t.files("probe-receipt")) == 1
    row = t.scenario.store().read_ledger()[0].rows[-1]
    assert row.evidence is lr.LedgerEvidence.RECEIPT_VERIFIED and row.outcome == "PROBED"
    assert t.status(subcell) is pc.SubcellStatus.CLEANUP_UNRESOLVED
    control = t.control(tmp_path)
    control.client.by_operation = {
        "list_tasks": [LISTED_PROBE],
        "describe_tasks": [STOPPED],
    }
    assert t.cleanup(control, []) == tool.EXIT_EXECUTED
    assert t.status(subcell) is pc.SubcellStatus.PASSED
    # An unexpected session (a 200): INVERTED, and the held task is stopped at once.
    t2 = _ProbeTool(tmp_path / "two")
    t2.ecs.descriptions = t2.descriptions(44)
    authorization = t2.authorize(subcell, t2.prepare(subcell))
    t2.client.by_operation = {"execute_command": [OK], "stop_task": [OK]}
    assert t2.main(*t2.execute_argv(subcell, authorization)) == tool.EXIT_INVERTED
    capsys.readouterr()
    record = pc.parse_permission_record(t2.files("permission-record")[0].read_bytes())
    assert record.outcome is pc.SubcellOutcome.INVERTED and record.operations == 2
    assert record.stop_acknowledged_ids == (TASK_ID,)
    assert [c[0] for c in t2.client.calls] == ["execute_command", "stop_task"]
    assert t2.status(subcell) is pc.SubcellStatus.FAILED
    # An answer that decides nothing (an InvalidParameterException, a task not running):
    # UNDECIDED, never MATCHED.
    t3 = _ProbeTool(tmp_path / "three")
    t3.ecs.descriptions = t3.descriptions(44)
    authorization = t3.authorize(subcell, t3.prepare(subcell))
    t3.client.by_operation = {"execute_command": [INVALID_PARAMETER]}
    assert t3.main(*t3.execute_argv(subcell, authorization)) == tool.EXIT_UNDECIDED
    capsys.readouterr()
    assert t3.status(subcell) is pc.SubcellStatus.UNDECIDED
    # A held launch that never reached its release (misplaced): no check, no record, the
    # attempt interrupted; the cleanup discovers the task by the reservation's tag.
    t4 = _ProbeTool(tmp_path / "four")
    t4.ecs.descriptions = [t4._task(status="RUNNING", subnet_id="subnet-0ffffffffffffffff")] * 2
    authorization = t4.authorize(subcell, t4.prepare(subcell))
    assert t4.main(*t4.execute_argv(subcell, authorization)) == tool.EXIT_PROBE_LAUNCHED
    capsys.readouterr()
    assert t4.files("permission-record") == [] and t4.client.calls == []
    assert t4.status(subcell) is pc.SubcellStatus.INTERRUPTED
    held = pc.parse_held_task_evidence(t4.files("held-task")[0].read_bytes())
    assert held.check is HeldCheckOutcome.NOT_APPLICABLE and held.last_status is None


def test_a_probe_subcell_needs_the_registered_probe_target_and_the_actor_s_identities(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    t = _ProbeTool(tmp_path)
    subcell = "R5-PUT-SILVER-TASK"
    # The build actor's subcell on the acquisition tool: the human bootstrap proves the
    # build actor's identities from the build binding, through the launch clients of
    # the wrong actor -- refused at the identity, nothing launched.
    authorization = t.authorize(subcell, t.prepare(subcell))
    assert t.main(*t.execute_argv(subcell, authorization)) == tool.EXIT_REFUSED_IDENTITY
    assert t.ecs.names("run_task") == [] and t.files("permission-attempt") == []
    capsys.readouterr()
    # A registration without the probe target: preparation and execution refuse.
    t2 = _Tool(tmp_path / "plain")
    assert (
        t2.main("--prepare-subcell", "R4-SECRET-GET-TASK", *t2.base()) == tool.EXIT_REFUSED_BINDING
    )
    # Automation and the wrong flag refuse before anything.
    assert t.main(
        *t.execute_argv("R4-SECRET-GET-TASK", authorization), modules={"pytest": object()}
    ) == (tool.EXIT_REFUSED_EXECUTION_CONTEXT)
    assert (
        t.main("--complete-subcell", "R4-SECRET-GET-TASK", *t.base()) == tool.EXIT_REFUSED_ARGUMENTS
    )
    assert t.main("--receipt-lines", "x", *t.base()) == tool.EXIT_REFUSED_ARGUMENTS
    assert t.main("--task", "x") == tool.EXIT_REFUSED_ARGUMENTS


def test_the_matrix_reads_a_launched_probe_as_inconclusive_and_a_completed_one_as_passed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    subcell = "R4-SECRET-GET-TASK"
    from test_production_verification_cells import _Cells

    cells = _Cells(tmp_path / "cells")
    t = _ProbeTool(tmp_path / "tool", scenario=cells.scenario)
    authorization = t.authorize(subcell, t.prepare(subcell))
    assert t.main(*t.execute_argv(subcell, authorization)) == tool.EXIT_PROBE_LAUNCHED
    capsys.readouterr()

    def context_source(_arguments: Any) -> pc.PermissionContext:
        return t.context()

    assert cells.main(*cells.base(), permission_context_source=context_source) == runner.EXIT_MATRIX
    out = capsys.readouterr().out
    assert "cell=R4-ACQUISITION ref=R-4 kind=PERMISSION_MATRIX status=INCONCLUSIVE" in out
    assert "  subcell=R4-SECRET-GET-TASK status=AWAITING_RECEIPT" in out
    assert "cell=R8-DELETION ref=R-8 kind=PERMISSION_MATRIX status=BLOCKED" in out
    for canary in CANARIES:
        assert canary not in out


# ---------------------------------------------------------------------------
# Correction 1: interruption and recovery, complete evidence binding, the held precondition
# ---------------------------------------------------------------------------


@dataclass
class _EcsFailingAfter(FakeEcs):
    """A FakeEcs whose ``DescribeTasks`` fails after the first ``n`` descriptions."""

    fail_after_describes: int = 1
    describes: int = 0

    def describe_tasks(self, **kwargs: Any) -> dict[str, Any]:
        self.describes += 1
        if self.describes > self.fail_after_describes:
            raise FakeClientError("ServerException")
        return super().describe_tasks(**kwargs)


class _Crash(BaseException):
    """A process interruption: what a KeyboardInterrupt or a power loss looks like to the
    tool -- nothing below an ``except Exception`` sees it, and nothing after it runs."""


def _crash_store(
    monkeypatch: pytest.MonkeyPatch, method: str, *, when: Callable[..., bool]
) -> None:
    """Interrupt the process inside the given store method when ``when`` says so."""
    from kalpamani.data.production.sharadar.launch_store import LaunchStore

    original = getattr(LaunchStore, method)

    def crashing(self: Any, *args: Any, **kwargs: Any) -> Any:
        if when(*args, **kwargs):
            raise _Crash(method)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(LaunchStore, method, crashing)


@pytest.mark.parametrize("subcell", ["R4-SECRET-GET-TASK", "R6-ACQ-EXECUTE-COMMAND"])
def test_a_probe_launch_interrupted_after_run_task_is_attributable_recoverable_and_settled(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    subcell: str,
) -> None:
    """Interrupted after RunTask, before any launch publication (finding 1): the
    authorization stays consumed, the reservation written before RunTask attributes the
    started task to the attempt, the cleanup discovers it by the reservation's tag with
    no post-launch record, recovery records the ledger row offline without relaunching,
    and nothing is retried."""
    t = _ProbeTool(tmp_path)
    if subcell.endswith("EXECUTE-COMMAND"):
        t.ecs.descriptions = t.descriptions(44)
        t.client.by_operation = {"execute_command": [SERVICE_DENIED]}
    authorization = t.authorize(subcell, t.prepare(subcell))
    _crash_store(
        monkeypatch, "write_record", when=lambda prefix, *_a, **_k: prefix == "launch-evidence"
    )
    with pytest.raises(_Crash):
        t.main(*t.execute_argv(subcell, authorization))
    monkeypatch.undo()
    capsys.readouterr()
    assert len(t.ecs.names("run_task")) == 1
    assert t.files("launch-record") == [] and t.files("launch-evidence") == []
    assert t.files("permission-record") == [] and len(t.files("permission-attempt")) == 1
    store = t.scenario.store()
    ledger = store.read_ledger()[0]
    identity = pp.probe_identity(t.probe_input().stamp)
    assert store.unreconciled(ledger) == [identity]
    reservation = store.reservation(identity)
    assert reservation is not None
    attempt = pc.parse_permission_attempt(t.files("permission-attempt")[0].read_bytes())
    workload = reservation.specification.workload
    assert workload["attempt_sha256"] == attempt.digest and workload["subcell_id"] == subcell
    assert workload["started_by"] == pc.started_by_of(attempt.stamp)
    assert workload["hold_seconds"] == (tool.PROBE_HOLD_SECONDS if "EXECUTE" in subcell else 0)
    # No re-execution and no second RunTask: the pending recovery refuses first, and the
    # consumed authorization refuses once the recovery is recorded (below).
    assert t.main(*t.execute_argv(subcell, authorization)) == tool.EXIT_REFUSED_RECOVERY_PENDING
    assert len(t.ecs.names("run_task")) == 1
    assert t.status(subcell) is pc.SubcellStatus.INTERRUPTED
    assert "recover-probe-launch" in t.state(subcell).reason
    # Any other probe launch refuses while the interrupted one awaits recovery, before
    # its authorization is consumed.
    other = "R4-PUT-INDEX-TASK"
    other_authorization = t.authorize(other, t.prepare(other), name="other-authorization.json")
    assert t.main(*t.execute_argv(other, other_authorization)) == tool.EXIT_REFUSED_RECOVERY_PENDING
    assert not store.is_consumed(
        tool.CONSUMPTION_KIND,
        pc.parse_permission_authorization(
            other_authorization.read_bytes(),
            subcell_id=other,
            statement_sha256=None,
            now=t.clock.now(),
        ).digest,
    )
    capsys.readouterr()
    # The cleanup accounts for the potentially started probe from the reservation alone:
    # discovery by the reservation's tag on the reservation's cluster, bounded, and the
    # task confirmed STOPPED by exact identity; no RunTask.
    control = t.control(tmp_path)
    control.client.by_operation = {"list_tasks": [LISTED_PROBE], "describe_tasks": [STOPPED]}
    assert t.cleanup(control, []) == tool.EXIT_EXECUTED
    listed = [kw for name, kw in control.client.calls if name == "list_tasks"]
    assert listed and listed[0]["started_by"] == workload["started_by"]
    assert listed[0]["cluster_arn"] == reservation.specification.placement["cluster_arn"]
    assert [c[0] for c in control.client.calls] == ["list_tasks", "describe_tasks"]
    cleanup = pc.parse_permission_cleanup(t.files("permission-cleanup")[0].read_bytes())
    assert cleanup.tasks[0].attempt_sha256 == attempt.digest and cleanup.tasks[0].settled
    assert cleanup.tasks[0].stopped_ids == (TASK_ID,)
    # An unresolved discovery stays explicit: a listing that fails settles nothing.
    control2 = t.control(tmp_path / "second-control")
    control2.client.by_operation = {"list_tasks": [TIMEOUT]}
    assert t.cleanup(control2, []) == tool.EXIT_CLEANUP_UNRESOLVED
    capsys.readouterr()
    # Recovery: the ledger row from the reservation (HALTED, exit-code-only), offline,
    # repeatable, no relaunch, nothing removed; the attempt stays interrupted.
    assert t.main("--recover-probe-launch", subcell, *t.base()) == tool.EXIT_RECOVERED
    out = capsys.readouterr().out
    assert tool.SENTENCES["recovered"] in out and "ledger_outcome=HALTED" in out
    row = store.read_ledger()[0].row(identity)
    assert row is not None and row.outcome == "HALTED"
    assert (
        row.evidence is lr.LedgerEvidence.EXIT_CODE_ONLY
        and row.launched_at == reservation.reserved_at
    )
    assert store.unreconciled(store.read_ledger()[0]) == []
    assert store.reservation(identity) is not None and len(t.ecs.names("run_task")) == 1
    assert t.main("--recover-probe-launch", subcell, *t.base()) == tool.EXIT_REFUSED_RECOVERY
    assert t.status(subcell) is pc.SubcellStatus.INTERRUPTED
    assert (
        t.main(*t.execute_argv(subcell, authorization)) == tool.EXIT_REFUSED_AUTHORIZATION_CONSUMED
    )
    assert len(t.ecs.names("run_task")) == 1
    capsys.readouterr()
    # With the recovery recorded, the other subcell launches (its own reservation).
    assert t.main(*t.execute_argv(other, other_authorization)) == tool.EXIT_PROBE_LAUNCHED
    capsys.readouterr()
    for canary in (*CANARIES, "arn:aws:ecs"):
        assert canary not in out


def test_a_probe_launch_interrupted_after_its_record_recovers_from_the_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Interrupted after the launch record, before the ledger: recovery reads the record
    (a task started, its observed exit) rather than inventing; a record naming another
    specification refuses."""
    t = _ProbeTool(tmp_path)
    subcell = "R4-SECRET-GET-TASK"
    authorization = t.authorize(subcell, t.prepare(subcell))
    _crash_store(monkeypatch, "replace_ledger", when=lambda *_a, **_k: True)
    with pytest.raises(_Crash):
        t.main(*t.execute_argv(subcell, authorization))
    monkeypatch.undo()
    capsys.readouterr()
    assert len(t.files("launch-record")) == 1
    identity = pp.probe_identity(t.probe_input().stamp)
    store = t.scenario.store()
    assert store.unreconciled(store.read_ledger()[0]) == [identity]
    assert t.status(subcell) is pc.SubcellStatus.INTERRUPTED
    # A launch record altered to another placement is not this reservation's launch.
    launch_path = t.files("launch-record")[0]
    kept = launch_path.read_bytes()
    document = json.loads(kept)
    document["subnet_id"] = "subnet-0ffffffffffffffff"
    launch_path.write_bytes(json.dumps(document).encode())
    assert t.main("--recover-probe-launch", subcell, *t.base()) == tool.EXIT_REFUSED_RECOVERY
    launch_path.write_bytes(kept)
    assert t.main("--recover-probe-launch", subcell, *t.base()) == tool.EXIT_RECOVERED
    assert "ledger_outcome=PROBED" in capsys.readouterr().out
    row = store.read_ledger()[0].row(identity)
    assert row is not None and row.evidence is lr.LedgerEvidence.EXIT_CODE_ONLY
    assert row.launched_at == lr.parse_launch_record(kept).launched_at
    # Recovered, the launched attempt completes from its receipt like any other.
    assert t.status(subcell) is pc.SubcellStatus.AWAITING_RECEIPT
    assert t.complete(subcell, t.receipt_lines(TaskOutcome.PROBE_MATCHED)) == tool.EXIT_COMPLETED


def test_a_completion_interrupted_before_the_ledger_is_repeatable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Interrupted between the permission record and the ledger replacement: the same
    completion, repeated with the same receipt, writes exactly what is missing; a
    different receipt refuses; nothing is relaunched and no evidence is removed."""
    t = _ProbeTool(tmp_path)
    subcell = "R4-SECRET-GET-TASK"
    authorization = t.authorize(subcell, t.prepare(subcell))
    assert t.main(*t.execute_argv(subcell, authorization)) == tool.EXIT_PROBE_LAUNCHED
    receipt = t.receipt_lines(TaskOutcome.PROBE_MATCHED)
    _crash_store(monkeypatch, "replace_ledger", when=lambda *_a, **_k: True)
    with pytest.raises(_Crash):
        t.complete(subcell, receipt)
    monkeypatch.undo()
    capsys.readouterr()
    assert len(t.files("permission-record")) == 1 and len(t.files("probe-receipt")) == 1
    row = t.scenario.store().read_ledger()[0].rows[-1]
    assert row.evidence is lr.LedgerEvidence.EXIT_CODE_ONLY
    # The matrix does not read the partial completion as PASSED.
    assert t.status(subcell) is pc.SubcellStatus.UNBOUND
    assert "LEDGER_MISMATCH" in t.state(subcell).reason
    # A different receipt for the same attempt refuses; the same one repairs.
    assert t.complete(subcell, t.receipt_lines(TaskOutcome.PROBE_MATCHED, operations=2)) == (
        tool.EXIT_REFUSED_COMPLETION
    )
    assert t.complete(subcell, receipt) == tool.EXIT_COMPLETED
    assert len(t.files("permission-record")) == 1 and len(t.files("probe-receipt")) == 1
    row = t.scenario.store().read_ledger()[0].rows[-1]
    assert row.evidence is lr.LedgerEvidence.RECEIPT_VERIFIED and row.outcome == "PROBED"
    assert t.complete(subcell, receipt) == tool.EXIT_COMPLETION_RECORDED
    assert len(t.ecs.names("run_task")) == 1
    capsys.readouterr()
    # Interrupted before the receipt evidence, after the record: the repeat writes the
    # evidence and completes the row.
    t2 = _ProbeTool(tmp_path / "two")
    authorization = t2.authorize(subcell, t2.prepare(subcell))
    assert t2.main(*t2.execute_argv(subcell, authorization)) == tool.EXIT_PROBE_LAUNCHED
    receipt = t2.receipt_lines(TaskOutcome.PROBE_MATCHED)
    _crash_store(
        monkeypatch, "write_record", when=lambda prefix, *_a, **_k: prefix == "probe-receipt"
    )
    with pytest.raises(_Crash):
        t2.complete(subcell, receipt)
    monkeypatch.undo()
    capsys.readouterr()
    assert len(t2.files("permission-record")) == 1 and t2.files("probe-receipt") == []
    assert t2.status(subcell) is pc.SubcellStatus.AWAITING_RECEIPT
    assert t2.complete(subcell, receipt) == tool.EXIT_COMPLETED
    assert len(t2.files("probe-receipt")) == 1
    assert t2.status(subcell) is pc.SubcellStatus.CLEANUP_UNRESOLVED


def _passed_probe(tmp_path: Path, subcell: str) -> _ProbeTool:
    """A valid, complete, cleaned-up probe subcell: the control every mutation is beside."""
    t = _ProbeTool(tmp_path)
    held = subcell.endswith("EXECUTE-COMMAND")
    if held:
        t.ecs.descriptions = t.descriptions(44)
        t.client.by_operation = {"execute_command": [SERVICE_DENIED]}
    authorization = t.authorize(subcell, t.prepare(subcell))
    code = t.main(*t.execute_argv(subcell, authorization))
    assert code == (tool.EXIT_EXECUTED if held else tool.EXIT_PROBE_LAUNCHED)
    receipt = (
        t.receipt_lines(TaskOutcome.PROBE_HELD, **HELD_BLOCK)
        if held
        else t.receipt_lines(TaskOutcome.PROBE_MATCHED)
    )
    assert t.complete(subcell, receipt) == tool.EXIT_COMPLETED
    control = t.control(tmp_path)
    control.client.by_operation = {"list_tasks": [LISTED_PROBE], "describe_tasks": [STOPPED]}
    assert t.cleanup(control, []) == tool.EXIT_EXECUTED
    assert t.status(subcell) is pc.SubcellStatus.PASSED
    return t


@pytest.mark.parametrize("subcell", ["R4-SECRET-GET-TASK", "R6-ACQ-EXECUTE-COMMAND"])
def test_a_passed_probe_subcell_loses_passed_when_its_launch_receipt_or_ledger_evidence_moves(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], subcell: str
) -> None:
    """Finding 2: removing, substituting, duplicating or contradicting the launch, receipt,
    reservation, ledger or held-task evidence of a valid completion never preserves
    PASSED, through the public runner, beside the untouched control."""
    from test_production_verification_cells import _Cells

    cells = _Cells(tmp_path / "cells")
    t = _ProbeTool(tmp_path / "tool", scenario=cells.scenario)
    held = subcell.endswith("EXECUTE-COMMAND")
    if held:
        t.ecs.descriptions = t.descriptions(44)
        t.client.by_operation = {"execute_command": [SERVICE_DENIED]}
    authorization = t.authorize(subcell, t.prepare(subcell))
    t.main(*t.execute_argv(subcell, authorization))
    receipt = (
        t.receipt_lines(TaskOutcome.PROBE_HELD, **HELD_BLOCK)
        if held
        else t.receipt_lines(TaskOutcome.PROBE_MATCHED)
    )
    assert t.complete(subcell, receipt) == tool.EXIT_COMPLETED
    control = t.control(tmp_path / "tool")
    control.client.by_operation = {"list_tasks": [LISTED_PROBE], "describe_tasks": [STOPPED]}
    assert t.cleanup(control, []) == tool.EXIT_EXECUTED
    capsys.readouterr()

    def matrix_status() -> str:
        cells.main(*cells.base(), permission_context_source=lambda _a: t.context())
        out = capsys.readouterr().out
        line = next(ln for ln in out.splitlines() if f"subcell={subcell} status=" in ln)
        return line.split("status=")[1].split()[0]

    assert matrix_status() == "PASSED"  # the valid control
    store = t.scenario.store()
    launch_path = t.files("launch-record")[0]
    launch_bytes = launch_path.read_bytes()
    receipt_path = t.files("probe-receipt")[0]
    receipt_bytes = receipt_path.read_bytes()
    identity = pp.probe_identity(t.probe_input().stamp)
    reservation_path = store.reservation_path(identity)
    reservation_bytes = reservation_path.read_bytes()

    def restore() -> None:
        launch_path.write_bytes(launch_bytes)
        receipt_path.write_bytes(receipt_bytes)
        reservation_path.write_bytes(reservation_bytes)
        for stray in t.scenario.records.glob("*-stray*.json"):
            stray.unlink()
        assert matrix_status() == "PASSED"

    def altered(raw: bytes, **fields: Any) -> bytes:
        document = json.loads(raw)
        document.update(fields)
        return json.dumps(document).encode()

    # Launch evidence: removed, substituted (placement, image, identity, input), duplicated.
    launch_path.unlink()
    assert matrix_status() == "UNBOUND" and "LAUNCH_MISSING" in t.state(subcell).reason
    launch_path.write_bytes(launch_bytes)
    for name, fields in (
        ("placement", {"subnet_id": "subnet-0ffffffffffffffff"}),
        ("image", {"image_digest": "sha256:" + "ab" * 32}),
        ("input", {"input_digest": "cd" * 32}),
        ("exit", {"observed_exit_code": 41 if held else 43}),
    ):
        launch_path.write_bytes(altered(launch_bytes, **fields))
        assert matrix_status() != "PASSED", name
    restore()
    (launch_path.parent / launch_path.name.replace(".json", "-stray.json")).write_bytes(
        launch_bytes
    )
    assert matrix_status() == "UNBOUND" and "LAUNCH_DUPLICATE" in t.state(subcell).reason
    restore()
    # A probe launch record no reservation attributes: unattributable, never adopted.
    stray = json.loads(launch_bytes)
    stray["identity"] = "probe-20260101T000000Z-ffff"
    (launch_path.parent / launch_path.name.replace(".json", "-stray.json")).write_bytes(
        json.dumps(stray).encode()
    )
    assert matrix_status() == "UNBOUND" and "no reservation attributes" in t.state(subcell).reason
    restore()
    # The reservation: removed (the launch is unattributable), altered (unbound).
    reservation_path.unlink()
    assert matrix_status() == "UNBOUND"
    reservation_path.write_bytes(reservation_bytes)
    reservation = json.loads(reservation_bytes)
    reservation["specification"]["workload"]["attempt_sha256"] = "ee" * 32
    reservation["specification_digest"] = lr.parse_specification(
        reservation["specification"]
    ).digest
    reservation_path.write_bytes(json.dumps(reservation).encode())
    assert matrix_status() == "UNBOUND" and "LAUNCH_MISSING" in t.state(subcell).reason
    # A reservation whose digest does not match its specification is malformed: the
    # runner refuses the whole matrix rather than reading around it.
    reservation["specification_digest"] = "ff" * 32
    reservation_path.write_bytes(json.dumps(reservation).encode())
    assert (
        cells.main(*cells.base(), permission_context_source=lambda _a: t.context())
        == runner.EXIT_REFUSED_RECORDS
    )
    capsys.readouterr()
    restore()
    # Receipt evidence: removed (awaiting, never PASSED), altered, duplicated, another
    # launch's.
    receipt_path.unlink()
    assert matrix_status() == "AWAITING_RECEIPT"
    receipt_path.write_bytes(receipt_bytes)
    document = json.loads(receipt_bytes)
    document["receipt"]["outcome"] = "PROBE_UNDECIDED" if not held else "PROBE_MATCHED"
    receipt_path.write_bytes(json.dumps(document).encode())
    assert matrix_status() == "UNBOUND" and "RECEIPT_INVALID" in t.state(subcell).reason
    receipt_path.write_bytes(altered(receipt_bytes, launch_record_sha256="11" * 32))
    assert matrix_status() == "UNBOUND" and "RECEIPT_MISMATCH" in t.state(subcell).reason
    restore()
    (receipt_path.parent / receipt_path.name.replace(".json", "-stray.json")).write_bytes(
        receipt_bytes
    )
    assert matrix_status() == "UNBOUND" and "RECEIPT_DUPLICATE" in t.state(subcell).reason
    restore()
    # The ledger: the row reverted to exit-code-only, another outcome, removed.
    ledger, digest = store.read_ledger()
    row = ledger.row(identity)
    assert row is not None
    reverted = lr.OwnerLedgerRow(
        identity=row.identity,
        actor=row.actor,
        kind=row.kind,
        outcome="HALTED",
        evidence=lr.LedgerEvidence.EXIT_CODE_ONLY,
        launched_at=row.launched_at,
        completed_at=row.completed_at,
        slice=None,
        plan_digest=None,
    )
    others = tuple(r for r in ledger.rows if r.identity != identity)
    store.replace_ledger(lr.OwnerLedger(rows=(*others, reverted)), expected_digest=digest)
    assert matrix_status() == "UNBOUND" and "LEDGER_MISMATCH" in t.state(subcell).reason
    _ledger2, digest2 = store.read_ledger()
    store.replace_ledger(lr.OwnerLedger(rows=others), expected_digest=digest2)
    assert matrix_status() == "UNBOUND" and "LEDGER_MISSING" in t.state(subcell).reason
    _ledger3, digest3 = store.read_ledger()
    store.replace_ledger(lr.OwnerLedger(rows=(*others, row)), expected_digest=digest3)
    assert matrix_status() == "PASSED"
    if held:
        # The held-task evidence: removed, another task, not RUNNING, duplicated.
        held_path = t.files("held-task")[0]
        held_bytes = held_path.read_bytes()
        held_path.unlink()
        assert matrix_status() == "UNBOUND" and "HELD_EVIDENCE_MISSING" in t.state(subcell).reason
        held_path.write_bytes(altered(held_bytes, task_id="0" * 32))
        assert matrix_status() == "UNBOUND" and "HELD_EVIDENCE_MISMATCH" in t.state(subcell).reason
        held_path.write_bytes(
            altered(held_bytes, check="TASK_STOPPED", last_status="STOPPED", image_digest=None)
        )
        assert matrix_status() == "UNBOUND" and "HELD_TASK_NOT_RUNNING" in t.state(subcell).reason
        held_path.write_bytes(held_bytes)
        (held_path.parent / held_path.name.replace(".json", "-stray.json")).write_bytes(held_bytes)
        assert matrix_status() == "UNBOUND" and "HELD_EVIDENCE_DUPLICATE" in t.state(subcell).reason
        restore()
        # The receipt of a probe that did not hold (its bootstrap refused): the launcher's
        # denial decides nothing without an available probe.
        t.ecs.descriptions = t.descriptions(12)
        receipt_path.unlink()
        launch_path.write_bytes(altered(launch_bytes, observed_exit_code=12))
        _ledger4, digest4 = store.read_ledger()
        provisional = lr.OwnerLedgerRow(
            identity=row.identity,
            actor=row.actor,
            kind=row.kind,
            outcome="REFUSED",
            evidence=lr.LedgerEvidence.EXIT_CODE_ONLY,
            launched_at=row.launched_at,
            completed_at=row.completed_at,
            slice=None,
            plan_digest=None,
        )
        store.replace_ledger(lr.OwnerLedger(rows=(*others, provisional)), expected_digest=digest4)
        assert (
            t.complete(subcell, t.receipt_lines(TaskOutcome.REFUSED_INPUT)) == tool.EXIT_COMPLETED
        )
        assert matrix_status() == "UNDECIDED" and "did not hold" in t.state(subcell).reason
    for canary in CANARIES:
        assert canary not in capsys.readouterr().out


def test_the_held_check_needs_a_fresh_running_description_of_its_own_task(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Finding 3: pending or delayed startup, stopped before the check, an observation
    failure and a mismatching description make no check and never PASSED; one attempt,
    explicit accounting, unexpected-success cleanup, no capability enabled."""
    subcell = "R6-ACQ-EXECUTE-COMMAND"

    def held_of(t: _ProbeTool) -> pc.HeldTaskEvidence:
        return pc.parse_held_task_evidence(t.files("held-task")[0].read_bytes())

    # Delayed startup: PENDING at the release, RUNNING on a later fresh description.
    t = _ProbeTool(tmp_path / "delayed")
    t.ecs.descriptions = [
        t._task(status="PENDING"),
        t._task(status="PENDING"),
        t._task(status="RUNNING"),
        t._task(status="STOPPED", exit_code=44),
    ]
    authorization = t.authorize(subcell, t.prepare(subcell))
    t.client.by_operation = {"execute_command": [SERVICE_DENIED]}
    assert t.main(*t.execute_argv(subcell, authorization)) == tool.EXIT_EXECUTED
    capsys.readouterr()
    held = held_of(t)
    assert held.check is HeldCheckOutcome.INVOKED and held.describe_calls == 2
    assert [c[0] for c in t.client.calls] == ["execute_command"]
    assert t.ecs.names("run_task")[0]["enableExecuteCommand"] is False
    # Never RUNNING inside the ceiling: no check, UNDECIDED, one attempt, nothing enabled.
    t2 = _ProbeTool(tmp_path / "timeout")
    t2.ecs.descriptions = [t2._task(status="PENDING")] * 40 + [
        t2._task(status="STOPPED", exit_code=44)
    ]
    authorization = t2.authorize(subcell, t2.prepare(subcell))
    t2.client.by_operation = {"execute_command": [SERVICE_DENIED]}
    assert t2.main(*t2.execute_argv(subcell, authorization)) == tool.EXIT_UNDECIDED
    capsys.readouterr()
    assert t2.client.calls == [] and held_of(t2).check is HeldCheckOutcome.READINESS_TIMEOUT
    assert held_of(t2).describe_calls * 5.0 <= HELD_READY_CEILING_SECONDS
    record = pc.parse_permission_record(t2.files("permission-record")[0].read_bytes())
    assert record.outcome is pc.SubcellOutcome.UNDECIDED and record.operations == 0
    assert t2.status(subcell) is pc.SubcellStatus.UNDECIDED
    assert "READINESS_TIMEOUT" in t2.state(subcell).reason
    assert len(t2.ecs.names("run_task")) == 1
    # Stopped before the check: no check, UNDECIDED.
    t3 = _ProbeTool(tmp_path / "stopped")
    t3.ecs.descriptions = [
        t3._task(status="PENDING"),
        t3._task(status="STOPPED", exit_code=12),
        t3._task(status="STOPPED", exit_code=12),
    ]
    authorization = t3.authorize(subcell, t3.prepare(subcell))
    t3.client.by_operation = {"execute_command": [SERVICE_DENIED]}
    assert t3.main(*t3.execute_argv(subcell, authorization)) == tool.EXIT_UNDECIDED
    capsys.readouterr()
    assert t3.client.calls == [] and held_of(t3).check is HeldCheckOutcome.TASK_STOPPED
    assert (
        t3.status(subcell) is pc.SubcellStatus.UNDECIDED
        and "TASK_STOPPED" in t3.state(subcell).reason
    )
    control = t3.control(tmp_path / "stopped")
    control.client.by_operation = {"list_tasks": [LISTED_PROBE], "describe_tasks": [STOPPED]}
    assert t3.cleanup(control, []) == tool.EXIT_EXECUTED
    assert t3.status(subcell) is pc.SubcellStatus.UNDECIDED
    # Observation failure before RUNNING: no check; the launch reports it.
    t4 = _ProbeTool(tmp_path / "unobservable")
    t4.ecs = _EcsFailingAfter(
        run_response=t4.ecs.run_response,
        descriptions=[t4._task(status="PENDING")],
        fail_after_describes=1,
    )
    t4.launch_clients = FakeClients(actor=ACQ, ecs_fake=t4.ecs, ec2_fake=t4.ec2)
    authorization = t4.authorize(subcell, t4.prepare(subcell))
    t4.client.by_operation = {"execute_command": [SERVICE_DENIED]}
    assert t4.main(*t4.execute_argv(subcell, authorization)) == tool.EXIT_UNDECIDED
    out = capsys.readouterr().out
    assert "launch=OBSERVATION_FAILED" in out and t4.client.calls == []
    assert held_of(t4).check is HeldCheckOutcome.OBSERVATION_FAILED
    assert t4.status(subcell) is pc.SubcellStatus.UNDECIDED
    # A fresh description naming another revision: no check.
    t5 = _ProbeTool(tmp_path / "mismatch")
    running_elsewhere = t5._task(status="RUNNING")
    running_elsewhere["taskDefinitionArn"] = probe_revision_arn(ACQ).replace(":7", ":8")
    t5.ecs.descriptions = [
        t5._task(status="PENDING"),
        running_elsewhere,
        t5._task(status="STOPPED", exit_code=44),
    ]
    authorization = t5.authorize(subcell, t5.prepare(subcell))
    t5.client.by_operation = {"execute_command": [SERVICE_DENIED]}
    assert t5.main(*t5.execute_argv(subcell, authorization)) == tool.EXIT_UNDECIDED
    capsys.readouterr()
    assert t5.client.calls == [] and held_of(t5).check is HeldCheckOutcome.TASK_MISMATCH
    # The bootstrap refusal: the check was made against a RUNNING task whose receipt
    # then says its bootstrap refused; completing from that receipt reads UNDECIDED.
    t6 = _ProbeTool(tmp_path / "refused")
    t6.ecs.descriptions = t6.descriptions(12)
    authorization = t6.authorize(subcell, t6.prepare(subcell))
    t6.client.by_operation = {"execute_command": [SERVICE_DENIED]}
    assert t6.main(*t6.execute_argv(subcell, authorization)) == tool.EXIT_EXECUTED
    capsys.readouterr()
    assert t6.status(subcell) is pc.SubcellStatus.AWAITING_RECEIPT
    assert t6.complete(subcell, t6.receipt_lines(TaskOutcome.REFUSED_INPUT)) == tool.EXIT_COMPLETED
    assert t6.status(subcell) is pc.SubcellStatus.UNDECIDED
    assert "did not hold" in t6.state(subcell).reason
    # Unexpected success on a RUNNING task: the capability is closed at once.
    t7 = _ProbeTool(tmp_path / "success")
    t7.ecs.descriptions = t7.descriptions(44)
    authorization = t7.authorize(subcell, t7.prepare(subcell))
    t7.client.by_operation = {"execute_command": [OK], "stop_task": [OK]}
    assert t7.main(*t7.execute_argv(subcell, authorization)) == tool.EXIT_INVERTED
    capsys.readouterr()
    assert [c[0] for c in t7.client.calls] == ["execute_command", "stop_task"]
    assert (
        held_of(t7).check is HeldCheckOutcome.INVOKED
        and t7.status(subcell) is pc.SubcellStatus.FAILED
    )


# ---------------------------------------------------------------------------
# The real adapter at its intercepted transport, and the image's probe factories
# ---------------------------------------------------------------------------


class TestAdapterAndEntrypoint:
    def test_execute_command_is_sent_as_the_documented_interactive_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A fake HTTP 200 alone does not validate request compatibility: the serialized
        ExecuteCommand carries ``command`` and ``interactive: true`` -- the form ECS
        documents as the only one it initiates -- and an AccessDeniedException answer
        classifies as a denial through the real botocore error path."""
        from test_production_permission_cells import TestBoto3Adapter

        adapter, transport = TestBoto3Adapter()._adapter(monkeypatch)
        transport.script = [
            (
                400,
                json.dumps(
                    {"__type": "AccessDeniedException", "message": "synthetic refusal"}
                ).encode(),
            )
        ]
        cluster = "arn:aws:ecs:us-east-1:000000000000:cluster/synthetic-research-cluster"
        observation = adapter.execute_command(cluster_arn=cluster, task_arn=TASK_ARN)
        assert transport.sends == 1
        request = transport.requests[-1]
        assert (
            request.headers["X-Amz-Target"] == b"AmazonEC2ContainerServiceV20141113.ExecuteCommand"
        )
        body = json.loads(request.body)
        assert set(body) == {"cluster", "task", "command", "interactive"}
        assert body["interactive"] is True and body["command"] == "/bin/true"
        assert body["cluster"] == cluster and body["task"] == TASK_ARN
        assert pc.classify(observation) is r3.ObservedClass.DENIED_OTHER
        # The accepted S3 classifier would not have read the service code as a denial.
        assert r3.classify(observation) is r3.ObservedClass.AMBIGUOUS
        # The held subcell's issue: DENIED matches; a 200 (a session) inverts and stops.
        cell = pc.subcell("R6-ACQ-EXECUTE-COMMAND")
        target = replace(
            permission_context().resolve(cell, stamp="20260912T140000Z-abcd", prerequisites={}),
            task_arn=TASK_ARN,
        )
        transport.script = [
            (400, json.dumps({"__type": "AccessDeniedException", "message": "synthetic"}).encode())
        ]
        issue = pc.issue_subcell(cell, target=target, client=adapter, stamp="20260912T140000Z-abcd")
        assert issue.outcome is pp.SubcellOutcome.MATCHED and issue.started_task_ids == (TASK_ID,)
        transport.script = [
            (200, json.dumps({"session": {"sessionId": "s"}, "interactive": True}).encode()),
            (200, json.dumps({"task": {"taskArn": TASK_ARN}}).encode()),
        ]
        issue = pc.issue_subcell(cell, target=target, client=adapter, stamp="20260912T140000Z-abcd")
        assert issue.outcome is pp.SubcellOutcome.INVERTED and issue.operations == 2
        assert issue.stop_acknowledged_ids == (TASK_ID,)
        assert transport.requests[-1].headers["X-Amz-Target"] == (
            b"AmazonEC2ContainerServiceV20141113.StopTask"
        )

    def test_the_image_entrypoint_hands_a_probe_the_one_service_its_operation_names(
        self, tmp_path: Path
    ) -> None:
        import importlib.util

        # Loaded by path, as the entrypoint script's own tests load it: the image script is
        # not on the test import path and is not type-checked with the tests.
        spec = importlib.util.spec_from_file_location(
            "production_task_entrypoint_for_probe",
            Path(__file__).resolve().parents[2] / "scripts" / "production_task_entrypoint.py",
        )
        assert spec is not None and spec.loader is not None
        entrypoint = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entrypoint)

        built: list[Any] = []

        class Clients:
            def client(self, service: Any) -> Any:
                built.append(service)

                class Secrets:
                    def get_secret_value(self, **_kwargs: Any) -> dict[str, Any]:
                        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

                return Secrets()

        factories = entrypoint._factories(TaskEntry.ACQUISITION_PROBE, tmp_path, clients=Clients())
        from kalpamani.data.production.sharadar.permission_probe_entry import (
            PermissionProbeFactories,
        )

        assert type(factories) is PermissionProbeFactories
        client = factories.operation_client(pc.Operation.SECRET_GET)
        assert pc.classify(client.get_secret_value("s")) is r3.ObservedClass.OK_200
        assert [b.value for b in built] == ["secretsmanager"]
        assert pc.classify(client.get_object("b", "k")) is r3.ObservedClass.AMBIGUOUS
        assert [b.value for b in built] == ["secretsmanager"]
        # No transport, no spent-identity source and no build configuration exist on the
        # factories at all: there is no field one could arrive through.
        assert not any(
            name in PermissionProbeFactories.__dataclass_fields__
            for name in ("transport", "spent_identities", "secrets", "s3")
        )
