"""Correction 2 of PR #109 (proposed ADR-0050 s.8.4): a ``StopTask`` acknowledgement is not a
termination.

Reproduced on the correction-1 head through the public tool: on the MISPLACED and the
STALE_RELEASE paths a successful ``StopTask`` acknowledgement resolved the reservation
``STOPPED`` -- self-settled -- with no ``DescribeTasks`` afterwards, so the next launch (from
another records directory, under a new authorization) consumed and issued ``RunTask`` while
the stopped-but-unobserved task may still have been running. Closed here: after an
acknowledged stop the launcher observes the exact task within what is left of the one
observation bound; only an observed ``STOPPED`` settles (task state ``STOPPED``); a task still
running at the bound, or an observation that failed, is ``STOP_ACKNOWLEDGED`` -- unsettled,
the task identity kept -- and the accepted cleanup rule (the known task described
``STOPPED``) is the only other settlement; a refused stop stays ``STARTED_NOT_TERMINAL``.

Every answer is a fake's; the path is monkeypatched OPEN for this process only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import production_deletion_rehearsal_tool as rt
import pytest
from test_production_deletion_rehearsal_correction_1 import _another_records_dir
from test_production_deletion_rehearsal_path import _launch_fakes, _task
from test_production_deletion_rehearsal_tool import (
    _inputs_file,
    _prepare,
    _RehearsalClients,
    _rehearse,
    _run,
    _tool,
)
from test_production_permission_cells import (
    LISTED_NONE,
    OK,
    TIMEOUT,
    _Tool,
    tool,
)

from fixtures.production_runtime import TASK_ARN, TASK_ID
from kalpamani.data.production.sharadar import deletion_rehearsal as dr
from kalpamani.data.production.sharadar import deletion_rehearsal_launch as dl
from kalpamani.data.production.sharadar import r3_verification as r3


def _described(reservation: dl.RehearsalReservation, status: str) -> r3.Observation:
    """The control principal's DescribeTasks answer for the reservation's known task."""
    cluster = reservation.cluster_arn
    prefix, name = cluster.split(":cluster/")
    return r3.Observation(status=200, task_statuses=((f"{prefix}:task/{name}/{TASK_ID}", status),))


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> None:
    assert dr.REHEARSAL_PATH_OPEN is False
    monkeypatch.setattr(dr, "REHEARSAL_PATH_OPEN", True)


class _EcsFailingAfterStop:
    """An ECS fake whose ``DescribeTasks`` fails once ``StopTask`` was acknowledged."""

    def __init__(self, inner: Any, failure: str) -> None:
        self.inner = inner
        self.calls = inner.calls
        self.failure = failure
        self.stopped = False

    def run_task(self, **kwargs: Any) -> Any:
        return self.inner.run_task(**kwargs)

    def describe_tasks(self, **kwargs: Any) -> Any:
        if self.stopped:
            self.calls.append(("describe_tasks", kwargs))
            from fixtures.production_runtime import FakeClientError

            raise FakeClientError(self.failure)
        return self.inner.describe_tasks(**kwargs)

    def stop_task(self, **kwargs: Any) -> Any:
        self.stopped = True
        return self.inner.stop_task(**kwargs)

    def names(self, operation: str) -> list[dict[str, Any]]:
        return [kwargs for name, kwargs in self.calls if name == operation]


def _clients(*, stale_release: bool, descriptions: list[dict[str, Any]]) -> _RehearsalClients:
    """Launch fakes for a task that will be stopped: misplaced by image, or the release
    parameter already occupied; ``descriptions`` is what DescribeTasks answers."""
    clients = _RehearsalClients(launch=_launch_fakes())
    clients.launch.ecs.descriptions = descriptions
    if stale_release:
        clients.launch.ssm.values[dr.REHEARSAL_RELEASE_PARAMETER] = b"stale"
    return clients


def _running(stale_release: bool) -> dict[str, Any]:
    if stale_release:
        return _task("RUNNING")
    return _task("RUNNING", image_digest="sha256:" + "ab" * 32)


def _launch_stopped(
    t: _Tool, inputs: Path, clients: _RehearsalClients, name: str
) -> tuple[int, str]:
    digest = _prepare(t, "R8-GET")
    authorization = t.authorize("R8-GET", digest, name=name)
    return _rehearse(t, "R8-GET", clients, inputs, authorization)


def _prepare_in(t: _Tool, base: list[str], name: str) -> Path:
    code, out = _run(t, "--prepare-rehearsal", "R8-GET", *base)
    assert code == tool.EXIT_PREPARED, out
    digest = out.split("statement_sha256=")[1].split()[0]
    return t.authorize("R8-GET", digest, name=name)


def _launch_from(
    t: _Tool, base: list[str], inputs: Path, authorization: Path
) -> tuple[int, str, _RehearsalClients]:
    again = _RehearsalClients(launch=_launch_fakes())
    code, out = _run(
        t,
        "--rehearse-deletion",
        "R8-GET",
        *base,
        "--rehearsal-inputs",
        str(inputs),
        "--authorization",
        str(authorization),
        tool.AUTHORIZATION_FLAG,
        launch_clients=again,
        monotonic=again.launch.clock.monotonic,
        sleep=again.launch.clock.sleep,
        now=again.launch.clock.now,
    )
    return code, out, again


def _calls_after_stop(clients: _RehearsalClients) -> list[str]:
    calls = [c[0] for c in clients.launch.ecs.calls]
    assert calls.count("stop_task") == 1
    return calls[calls.index("stop_task") + 1 :]


class TestAcknowledgedButRunning:
    @pytest.mark.parametrize("stale_release", [False, True], ids=["misplaced", "stale-release"])
    def test_an_acknowledged_stop_of_a_task_still_running_settles_nothing(
        self, tmp_path: Path, opened: None, stale_release: bool
    ) -> None:
        t = _tool(tmp_path)
        inputs = _inputs_file(t)
        clients = _clients(stale_release=stale_release, descriptions=[_running(stale_release)])
        code, out = _launch_stopped(t, inputs, clients, "auth-1.json")
        expected = "STALE_RELEASE" if stale_release else "MISPLACED"
        assert code == rt.EXIT_REHEARSAL_NOT_LAUNCHED and f"launch={expected}" in out
        assert "task_state=STOP_ACKNOWLEDGED" in out
        assert "describe_task_after_stop:observation_exhausted" in out
        # The exact task was observed after the stop, within the one bound, and never seen
        # STOPPED; RunTask and StopTask each once.
        after = _calls_after_stop(clients)
        assert after and set(after) == {"describe_tasks"}
        calls = [c[0] for c in clients.launch.ecs.calls]
        assert calls.count("run_task") == 1
        describes = calls.count("describe_tasks")
        assert describes <= dl.MAX_OBSERVATION_READS
        assert clients.launch.clock.monotonic() <= dl.OBSERVATION_CEILING_SECONDS
        assert all(k["tasks"] == [TASK_ARN] for k in clients.launch.ecs.names("describe_tasks"))
        store = t.scenario.store()
        [reservation] = dl.rehearsal_reservations(store).values()
        [resolution] = dl.rehearsal_resolutions(store).values()
        assert resolution.outcome == expected
        assert resolution.task_state is dl.RehearsalTaskState.STOP_ACKNOWLEDGED
        assert resolution.task_id == TASK_ID and not resolution.self_settled
        assert len(dl.unsettled_rehearsals(store, t.evidence().cleanups)) == 1
        assert t.files("rehearsal-launch-record") == []
        # Every later launch is refused before its authorization is consumed -- from this
        # records directory and from another over the same ledger, under new
        # authorizations -- with no client call.
        main_authorization: Path | None = None
        for label, base in (("main", t.base()), ("other", _another_records_dir(t))):
            authorization = _prepare_in(t, base, f"auth-{label}.json")
            if label == "main":
                main_authorization = authorization
            code, out, again = _launch_from(t, base, inputs, authorization)
            assert code == tool.EXIT_REFUSED_RECOVERY_PENDING, out
            assert rt.SENTENCES["refused_rehearsal_recovery_pending"] in out
            assert again.launch.ecs.calls == [] and again.launch.ssm.calls == []
            assert len(t.scenario.store().consumptions(dr.REHEARSAL_CONSUMPTION_KIND)) == 1
        # Recovery is for an interrupted (unresolved) reservation only: nothing to recover.
        code, out = _run(t, "--recover-rehearsal-launch", "R8-GET", *t.base())
        assert code == tool.EXIT_REFUSED_RECOVERY
        # The cleanup describes the known task. Still RUNNING: stopped again by the control,
        # residue, not settled -- the block stands. (The R-4 object is answered with
        # timeouts so it stays the rehearsal's target.)
        control = t.control(tmp_path)
        control.clock.seconds = 1000.0
        assert t.cleanup(
            control, [TIMEOUT, TIMEOUT, LISTED_NONE, _described(reservation, "RUNNING"), OK]
        ) == (tool.EXIT_CLEANUP_UNRESOLVED)
        described = [c for c in control.client.calls if c[0] == "describe_tasks"]
        assert described and described[0][1]["task_arns"][0].endswith("/" + TASK_ID)
        assert len(dl.unsettled_rehearsals(store, t.evidence().cleanups)) == 1
        assert main_authorization is not None
        code, out, again = _launch_from(t, t.base(), inputs, main_authorization)
        assert code == tool.EXIT_REFUSED_RECOVERY_PENDING and again.launch.ecs.calls == []
        # Described STOPPED by a later verified cleanup: settled through the accepted rule;
        # the launch proceeds under the still-unconsumed authorization.
        control.clock.seconds += 60.0
        assert t.cleanup(
            control, [TIMEOUT, TIMEOUT, LISTED_NONE, _described(reservation, "STOPPED")]
        ) == (tool.EXIT_CLEANUP_UNRESOLVED)  # the object's residue; the task is settled
        assert dl.unsettled_rehearsals(store, t.evidence().cleanups) == []
        code, out, again = _launch_from(t, t.base(), inputs, main_authorization)
        assert code == rt.EXIT_REHEARSAL_LAUNCHED, out
        assert sum(1 for c in again.launch.ecs.calls if c[0] == "run_task") == 1


class TestObservationFailedOrExhausted:
    @pytest.mark.parametrize("stale_release", [False, True], ids=["misplaced", "stale-release"])
    @pytest.mark.parametrize("failure", ["AccessDeniedException", "timeout"])
    def test_a_failed_observation_after_the_stop_settles_nothing(
        self, tmp_path: Path, opened: None, stale_release: bool, failure: str
    ) -> None:
        t = _tool(tmp_path)
        inputs = _inputs_file(t)
        clients = _clients(stale_release=stale_release, descriptions=[_running(stale_release)])
        clients.launch.ecs = _EcsFailingAfterStop(clients.launch.ecs, failure)  # type: ignore[assignment]
        code, out = _launch_stopped(t, inputs, clients, "auth-1.json")
        assert code == rt.EXIT_REHEARSAL_NOT_LAUNCHED
        assert "task_state=STOP_ACKNOWLEDGED" in out and "describe_task_after_stop:" in out
        assert "observation_exhausted" not in out
        assert _calls_after_stop(clients) == ["describe_tasks"]
        store = t.scenario.store()
        [resolution] = dl.rehearsal_resolutions(store).values()
        assert resolution.task_state is dl.RehearsalTaskState.STOP_ACKNOWLEDGED
        assert resolution.task_id == TASK_ID
        assert len(dl.unsettled_rehearsals(store, t.evidence().cleanups)) == 1
        authorization = _prepare_in(t, t.base(), "auth-2.json")
        code, out, again = _launch_from(t, t.base(), inputs, authorization)
        assert code == tool.EXIT_REFUSED_RECOVERY_PENDING and again.launch.ecs.calls == []

    def test_a_refused_stop_stays_started_not_terminal(self, tmp_path: Path, opened: None) -> None:
        t = _tool(tmp_path)
        inputs = _inputs_file(t)
        clients = _clients(stale_release=False, descriptions=[_running(False)])
        clients.launch.ecs.stop_failure = "AccessDeniedException"
        code, out = _launch_stopped(t, inputs, clients, "auth-1.json")
        assert code == rt.EXIT_REHEARSAL_NOT_LAUNCHED and "task_state=STARTED_NOT_TERMINAL" in out
        assert "stop_task:" in out and _calls_after_stop(clients) == []
        [resolution] = dl.rehearsal_resolutions(t.scenario.store()).values()
        assert resolution.task_state is dl.RehearsalTaskState.STARTED_NOT_TERMINAL
        assert resolution.task_id == TASK_ID
        assert len(dl.unsettled_rehearsals(t.scenario.store(), t.evidence().cleanups)) == 1


class TestConfirmedTermination:
    @pytest.mark.parametrize("stale_release", [False, True], ids=["misplaced", "stale-release"])
    def test_an_observed_termination_after_the_stop_settles_by_observation(
        self, tmp_path: Path, opened: None, stale_release: bool
    ) -> None:
        t = _tool(tmp_path)
        inputs = _inputs_file(t)
        # RUNNING while placed and once more after the stop, then STOPPED.
        clients = _clients(
            stale_release=stale_release,
            descriptions=[
                _running(stale_release),
                _running(stale_release),
                _task("STOPPED", exit_code=None),
            ],
        )
        code, out = _launch_stopped(t, inputs, clients, "auth-1.json")
        assert code == rt.EXIT_REHEARSAL_NOT_LAUNCHED and "task_state=STOPPED" in out
        assert "describe_task_after_stop" not in out
        assert _calls_after_stop(clients) == ["describe_tasks", "describe_tasks"]
        store = t.scenario.store()
        [resolution] = dl.rehearsal_resolutions(store).values()
        assert resolution.task_state is dl.RehearsalTaskState.STOPPED
        assert resolution.task_id == TASK_ID and resolution.self_settled
        assert dl.unsettled_rehearsals(store, t.evidence().cleanups) == []
        assert t.files("rehearsal-launch-record") == []
        # Settled by the launcher's own observation of the exact task: the next launch,
        # from another records directory too, proceeds.
        base = _another_records_dir(t)
        authorization = _prepare_in(t, base, "auth-2.json")
        code, out, _again = _launch_from(t, base, inputs, authorization)
        assert code == rt.EXIT_REHEARSAL_LAUNCHED, out
        assert len(t.scenario.store().consumptions(dr.REHEARSAL_CONSUMPTION_KIND)) == 2

    def test_the_post_stop_observation_shares_the_one_bound(
        self, tmp_path: Path, opened: None
    ) -> None:
        t = _tool(tmp_path)
        inputs = _inputs_file(t)
        clients = _clients(stale_release=True, descriptions=[_task("RUNNING")])
        # Spend most of the bound before the stop: the placement loop answers RUNNING with
        # no attachment interface until the very end is near.
        placing = _task("RUNNING", attachment_status=None)
        clients.launch.ecs.descriptions = [placing] * (dl.MAX_OBSERVATION_READS - 3) + [
            _task("RUNNING")
        ]
        code, out = _launch_stopped(t, inputs, clients, "auth-1.json")
        assert code == rt.EXIT_REHEARSAL_NOT_LAUNCHED and "task_state=STOP_ACKNOWLEDGED" in out
        calls = [c[0] for c in clients.launch.ecs.calls]
        assert calls.count("describe_tasks") == dl.MAX_OBSERVATION_READS
        assert calls.count("stop_task") == 1 and calls.count("run_task") == 1
