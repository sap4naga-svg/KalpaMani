"""The production human-binding materializer (ADR-0036 §2.5, G-4), on synthetic files only.

Two authorization objects, one per actor; a document that parses through the accepted
loader before a byte is written; a written artifact re-read through the accepted human
loader and removed if it does not reload; every private path from the environment; no AWS
identity verified -- an owner declaration is materialized, nothing is proved about it.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import pickle
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final

import pytest

from fixtures.production_runtime import CANARIES
from kalpamani.data.production.sharadar import bindings as pb
from kalpamani.data.production.sharadar.vocabulary import ProductionActor, constants_for
from kalpamani.data.qualify.sharadar import runtime_binding as rb

pytestmark = pytest.mark.unit

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
SCRIPT: Final = REPO_ROOT / "scripts" / "production_human_binding_materialize.py"
ACCOUNT: Final = "111111111111"
OTHER_ACCOUNT: Final = "000000000000"
BUCKET: Final = "synthetic-licensed-bucket"
ENVELOPE: Final = "ab" * 32
CURRENT: Final = "S-1-5-21-0-0-0-1001"
ACQ: Final = ProductionActor.ACQUISITION
BLD: Final = ProductionActor.BUILD


def _module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gate = _module("production_human_binding_materialize", SCRIPT)


def _security(_path: Path) -> rb.FileSecurity:
    return rb.FileSecurity(
        current_principal=CURRENT,
        owner=CURRENT,
        inheritance_disabled=True,
        allow_principals=(CURRENT,),
        deny_principals=(),
    )


def _environment_binding(**overrides: Any) -> rb.QualificationEnvironmentBinding:
    settled: dict[str, Any] = {
        "target_account_id": ACCOUNT,
        "licensed_bucket_name": BUCKET,
        "partition": rb.EXPECTED_PARTITION,
        "region": rb.EXPECTED_REGION,
        "digest": ENVELOPE,
    }
    settled.update(overrides)
    return rb.QualificationEnvironmentBinding(**settled)


class _Recorder:
    def __init__(self, *, fail: bool = False, returns: Any = None) -> None:
        self.writes: list[tuple[str, bytes]] = []
        self.fail = fail
        self.returns = returns

    def __call__(self, *, destination: str, payload: bytes) -> Path:
        if self.fail:
            raise OSError("the artifact was not created")
        self.writes.append((destination, payload))
        return Path(destination) if self.returns is None else self.returns


class _Bin:
    def __init__(self) -> None:
        self.removed: list[Path] = []

    def __call__(self, path: Path) -> None:
        self.removed.append(path)


class _Verifier:
    """Answers with the binding the recorder's bytes parse to, or what a test dictates."""

    def __init__(self, recorder: _Recorder, *, fail: bool = False, answer: Any = None) -> None:
        self.recorder = recorder
        self.fail = fail
        self.answer = answer
        self.calls: list[tuple[ProductionActor, str]] = []

    def __call__(self, *, actor: ProductionActor, destination: str) -> Any:
        self.calls.append((actor, destination))
        if self.fail:
            raise rb.RuntimeBindingError(rb.RuntimeBindingDefect.FILE_UNREADABLE)
        if self.answer is not None:
            return self.answer
        (_dest, payload) = self.recorder.writes[-1]
        return pb.parse_production_runtime_binding(json.loads(payload), actor=actor)


def _materialize(
    *,
    actor: ProductionActor = ACQ,
    authorization: object | None = None,
    recorder: _Recorder | None = None,
    verifier: _Verifier | None = None,
    modules: Mapping[str, object] | None = None,
    env: Mapping[str, str] | None = None,
    source: str = r"C:\synthetic\KalpaMani\private\environment.json",
    destinations: dict[ProductionActor, str] | None = None,
    account: str | None = ACCOUNT,
    loader: Callable[..., Any] | None = None,
    bin_: _Bin | None = None,
) -> tuple[Any, _Recorder, _Verifier, _Bin]:
    sink = recorder if recorder is not None else _Recorder()
    checker = verifier if verifier is not None else _Verifier(sink)
    bin_ = _Bin() if bin_ is None else bin_
    targets = destinations or {
        ACQ: r"C:\synthetic\KalpaMani\private\acquisition-binding.json",
        BLD: r"C:\synthetic\KalpaMani\private\build-binding.json",
    }
    outcome = gate.materialize_production_binding(
        authorization=(
            gate._MATERIALIZATION_AUTHORIZATIONS[actor] if authorization is None else authorization
        ),
        env={} if env is None else env,
        modules={} if modules is None else modules,
        source_path=lambda: source,
        destination_source=lambda a: targets[a],
        expected_account=lambda: account,
        load_environment_binding=(
            loader if loader is not None else (lambda **_kw: _environment_binding())
        ),
        write_artifact=sink,
        verify_binding=checker,
        discard_artifact=bin_,
    )
    return outcome, sink, checker, bin_


@pytest.mark.parametrize("actor", list(ProductionActor))
def test_a_materialization_writes_one_verified_binding_for_its_actor(
    actor: ProductionActor,
) -> None:
    (materialized, outcome), sink, checker, bin_ = _materialize(actor=actor)
    assert materialized is actor and outcome is gate.MaterializationOutcome.COMPLETED
    assert len(sink.writes) == 1 and len(checker.calls) == 1 and bin_.removed == []
    destination, payload = sink.writes[0]
    assert checker.calls == [(actor, destination)]
    document = json.loads(payload.decode("utf-8"))
    constants = constants_for(actor)
    assert document[constants.profile_field] == constants.profile
    assert document["contract_id"] == constants.binding_contract_id
    assert document["binding_kind"] == constants.binding_kind
    assert document["target_account_id"] == ACCOUNT
    assert document["licensed_bucket_name"] == BUCKET
    assert document["provenance"]["environment_binding_sha256"] == ENVELOPE
    assert document["provenance"]["implementation_commit"] == gate.IMPLEMENTATION_COMMIT
    assert document["provenance"]["implementation_tree"] == gate.IMPLEMENTATION_TREE
    # The other actor's profile field is absent; the other actor's loader refuses it.
    other = BLD if actor is ACQ else ACQ
    assert constants_for(other).profile_field not in document
    with pytest.raises(rb.RuntimeBindingError):
        pb.parse_production_runtime_binding(document, actor=other)
    assert payload == rb.canonical_binding_bytes(document)


def test_the_written_artifact_round_trips_through_the_accepted_human_loader(
    tmp_path: Path,
) -> None:
    root = tmp_path / "KalpaMani" / "private"
    root.mkdir(parents=True)
    source = root / "environment.json"
    payload = rb.canonical_binding_bytes(
        {
            "schema_version": rb.ENVIRONMENT_BINDING_SCHEMA_VERSION,
            "binding_kind": rb.ENVIRONMENT_BINDING_KIND,
            "contract_id": rb.ENVIRONMENT_BINDING_CONTRACT_ID,
            "aws_partition": rb.EXPECTED_PARTITION,
            "aws_region": rb.EXPECTED_REGION,
            "target_account_id": ACCOUNT,
            "licensed_bucket_name": BUCKET,
            "provenance": {
                "source_kind": rb.ENVIRONMENT_BINDING_SOURCE_KIND,
                "captured_at_utc": "2026-09-14T18:00:00Z",
                "outputs_digest": ENVELOPE,
            },
        }
    )
    source.write_bytes(payload)
    destination = root / "acquisition-binding.json"

    def loader(*, path: str, expected_account: str | None) -> Any:
        return rb.load_environment_binding(
            path=path,
            expected_account=expected_account,
            root_source=lambda: root,
            security_of=_security,
        )

    def writer(*, destination: str, payload: bytes) -> Path:
        target = Path(destination)
        with target.open("xb") as handle:
            handle.write(payload)
        return target

    def verifier(*, actor: ProductionActor, destination: str) -> Any:
        variable = constants_for(actor).binding_env_var
        return pb.load_human_runtime_binding(
            actor,
            environment=lambda name: destination if name == variable else None,
            root_source=lambda: root,
            security_of=_security,
        )

    (materialized, outcome) = gate.materialize_production_binding(
        authorization=gate._MATERIALIZATION_AUTHORIZATIONS[ACQ],
        env={},
        modules={},
        source_path=lambda: str(source),
        destination_source=lambda actor: str(destination),
        expected_account=lambda: ACCOUNT,
        load_environment_binding=loader,
        write_artifact=writer,
        verify_binding=verifier,
        discard_artifact=lambda path: path.unlink(),
    )
    assert materialized is ACQ and outcome is gate.MaterializationOutcome.COMPLETED
    loaded = verifier(actor=ACQ, destination=str(destination))
    assert loaded.target_account_id == ACCOUNT and loaded.licensed_bucket_name == BUCKET
    document = json.loads(destination.read_bytes())
    assert document["provenance"]["environment_binding_sha256"] == rb.sha256_hex(payload)
    # An occupied destination is a refusal, never a replacement.
    before = destination.read_bytes()
    with pytest.raises(gate.MaterializationError, match="not created"):
        gate.materialize_production_binding(
            authorization=gate._MATERIALIZATION_AUTHORIZATIONS[ACQ],
            env={},
            modules={},
            source_path=lambda: str(source),
            destination_source=lambda actor: str(destination),
            expected_account=lambda: ACCOUNT,
            load_environment_binding=loader,
            write_artifact=writer,
            verify_binding=verifier,
            discard_artifact=lambda path: path.unlink(),
        )
    assert destination.read_bytes() == before


REFUSALS: Final[tuple[tuple[str, dict[str, Any], Any], ...]] = (
    (
        "no authorization",
        {"authorization": object()},
        gate.MaterializationOutcome.REFUSED_NOT_AUTHORIZED,
    ),
    (
        "under a test runner",
        {"modules": {"pytest": object()}},
        gate.MaterializationOutcome.REFUSED_EXECUTION_CONTEXT,
    ),
    (
        "in CI",
        {"env": {"GITHUB_ACTIONS": "true"}},
        gate.MaterializationOutcome.REFUSED_EXECUTION_CONTEXT,
    ),
    ("no source path", {"source": "  "}, gate.MaterializationOutcome.REFUSED_SOURCE_PATH),
    (
        "no governed account",
        {"account": None},
        gate.MaterializationOutcome.REFUSED_EXPECTED_ACCOUNT,
    ),
    (
        "a source naming another account",
        {"account": OTHER_ACCOUNT},
        gate.MaterializationOutcome.REFUSED_ENVIRONMENT_BINDING,
    ),
    (
        "a source that refuses",
        {
            "loader": lambda **_kw: (_ for _ in ()).throw(
                rb.RuntimeBindingError(rb.RuntimeBindingDefect.FILE_EMPTY)
            )
        },
        gate.MaterializationOutcome.REFUSED_ENVIRONMENT_BINDING,
    ),
    (
        "a source in another region",
        {"loader": lambda **_kw: _environment_binding(region="eu-west-1")},
        gate.MaterializationOutcome.REFUSED_ENVIRONMENT_BINDING,
    ),
    (
        "no destination",
        {"destinations": {ACQ: "", BLD: ""}},
        gate.MaterializationOutcome.REFUSED_DESTINATION,
    ),
    (
        "a writer that fails",
        {"recorder": _Recorder(fail=True)},
        gate.MaterializationOutcome.REFUSED_WRITE,
    ),
)


@pytest.mark.parametrize(("label", "overrides", "expected"), REFUSALS, ids=[r[0] for r in REFUSALS])
def test_every_refusal_writes_nothing_and_names_its_outcome(
    label: str, overrides: dict[str, Any], expected: Any
) -> None:
    with pytest.raises(gate.MaterializationError) as caught:
        _materialize(**overrides)
    assert caught.value.outcome is expected
    recorder = overrides.get("recorder")
    if recorder is not None:
        assert recorder.writes == []


def test_a_written_artifact_the_loader_refuses_is_removed() -> None:
    sink = _Recorder()
    checker = _Verifier(sink, fail=True)
    bin_ = _Bin()
    with pytest.raises(gate.MaterializationError) as caught:
        _materialize(recorder=sink, verifier=checker, bin_=bin_)
    assert caught.value.outcome is gate.MaterializationOutcome.REFUSED_VERIFICATION
    assert bin_.removed == [Path(sink.writes[0][0])]


def test_a_reload_that_answers_for_the_other_actor_or_another_value_is_refused() -> None:
    for answer in (
        pb.ProductionRuntimeBinding(
            actor=BLD,
            target_account_id=ACCOUNT,
            licensed_bucket_name=BUCKET,
            partition=rb.EXPECTED_PARTITION,
            region=rb.EXPECTED_REGION,
            profile=constants_for(BLD).profile,
        ),
        pb.ProductionRuntimeBinding(
            actor=ACQ,
            target_account_id=OTHER_ACCOUNT,
            licensed_bucket_name=BUCKET,
            partition=rb.EXPECTED_PARTITION,
            region=rb.EXPECTED_REGION,
            profile=constants_for(ACQ).profile,
        ),
    ):
        sink = _Recorder()
        bin_ = _Bin()
        with pytest.raises(gate.MaterializationError) as caught:
            _materialize(recorder=sink, verifier=_Verifier(sink, answer=answer), bin_=bin_)
        assert caught.value.outcome is gate.MaterializationOutcome.REFUSED_VERIFICATION
        assert len(bin_.removed) == 1


def test_the_two_authorizations_are_distinct_singletons_that_cannot_be_forged() -> None:
    acquisition = gate._MATERIALIZATION_AUTHORIZATIONS[ACQ]
    build = gate._MATERIALIZATION_AUTHORIZATIONS[BLD]
    assert acquisition is not build
    assert gate._authorized_actor(acquisition) is ACQ and gate._authorized_actor(build) is BLD
    assert gate._authorized_actor(object()) is None
    with pytest.raises(TypeError):
        gate._BindingMaterializationAuthorization(ACQ)
    for operation in (copy.copy, copy.deepcopy, pickle.dumps):
        with pytest.raises(TypeError):
            operation(acquisition)
    with pytest.raises(TypeError):
        type("_Forged", (gate._BindingMaterializationAuthorization,), {})
    forged = object.__new__(gate._BindingMaterializationAuthorization)
    assert gate._authorized_actor(forged) is None


def test_the_cli_refuses_by_default_by_name_and_with_both_flags(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert gate.main([]) == 1
    assert gate.MaterializationOutcome.REFUSED_NOT_AUTHORIZED.value in capsys.readouterr().out
    for option in sorted(gate.REFUSED_OPTIONS):
        assert gate.main([option]) == 2
    flags = list(gate.AUTHORIZATION_FLAGS)
    assert gate.main(flags) == 2  # mutually exclusive
    assert gate.main(["--unknown"]) == 2
    # Under pytest the authorized path refuses at the execution context and writes nothing.
    assert gate.main([flags[0]]) == 3
    assert gate.MaterializationOutcome.REFUSED_EXECUTION_CONTEXT.value in capsys.readouterr().out


def test_no_output_or_refusal_carries_a_private_value(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(gate.MaterializationError) as caught:
        _materialize(account=OTHER_ACCOUNT)
    for outcome in gate.MaterializationOutcome:
        gate.emit(outcome)
    out = capsys.readouterr().out
    for surface in (out, str(caught.value), repr(caught.value)):
        for canary in (ACCOUNT, OTHER_ACCOUNT, BUCKET, ENVELOPE, *CANARIES):
            assert canary not in surface


def test_the_implementation_provenance_names_the_reviewed_contract_commit() -> None:
    assert len(gate.IMPLEMENTATION_COMMIT) == 40 and len(gate.IMPLEMENTATION_TREE) == 40
    status = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert gate.IMPLEMENTATION_COMMIT in status
    source = SCRIPT.read_text(encoding="utf-8")
    # Reaches no AWS service: no SDK import, no STS call, no client construction.
    assert "import boto3" not in source and "get_caller_identity" not in source
    # The constructor names are assembled so this guard is not itself a construction site.
    assert all("boto3." + suffix not in source for suffix in ("client(", "Session("))
