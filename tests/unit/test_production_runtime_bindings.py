"""Behavioural tests: the production bindings, the two deliveries, and the identity gate.

Everything here runs on synthetic documents and fakes. No file outside ``tmp_path``
is read, no environment variable is read, no socket is opened.
"""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path
from typing import Any, Final

import pytest

from fixtures.production_runtime import (
    ACCOUNT,
    BUCKET,
    CANARIES,
    OTHER_ACCOUNT,
    TASK_ID,
    binding_document,
    caller_identity,
    human_identity_arn,
    launcher_identity_arn,
    task_identity_arn,
)
from kalpamani.data.production.sharadar import bindings as pb
from kalpamani.data.production.sharadar import identity as pi
from kalpamani.data.production.sharadar import vocabulary as pv
from kalpamani.data.qualify.sharadar import runtime_binding as rb

ACTORS: Final = (pv.ProductionActor.ACQUISITION, pv.ProductionActor.BUILD)
CURRENT: Final = "S-1-5-21-0-0-0-1001"
OTHER_USER: Final = "S-1-5-21-0-0-0-1002"

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
INFRA: Final = PROJECT_ROOT / "infra" / "aws" / "research-data-plane"


def _security(**overrides: Any) -> rb.FileSecurity:
    fields: dict[str, Any] = {
        "current_principal": CURRENT,
        "owner": CURRENT,
        "inheritance_disabled": True,
        "allow_principals": (CURRENT,),
        "deny_principals": (),
    }
    fields.update(overrides)
    return rb.FileSecurity(**fields)


class _Reader:
    """A parameter reader answering one queued value, counting every read."""

    def __init__(self, values: dict[str, bytes], *, raising: Exception | None = None) -> None:
        self.values = values
        self.raising = raising
        self.reads: list[str] = []

    def read_parameter(self, name: str) -> bytes:
        self.reads.append(name)
        if self.raising is not None:
            raise self.raising
        return self.values[name]


# ---------------------------------------------------------------------------
# The vocabulary agrees with the merged Terraform declaration
# ---------------------------------------------------------------------------


class TestTheCompiledConstantsMatchTheDeclaration:
    @pytest.mark.parametrize("actor", ACTORS, ids=lambda a: a.value)
    def test_every_literal_appears_in_the_terraform_sources(
        self, actor: pv.ProductionActor
    ) -> None:
        sources = "\n".join(
            path.read_text(encoding="utf-8") for path in sorted(INFRA.glob("production_*.tf"))
        )
        constants = pv.constants_for(actor)
        for literal in (
            constants.permission_set,
            constants.launcher_permission_set,
            constants.task_role_name,
            constants.task_family,
            constants.profile,
            constants.binding_kind,
            constants.binding_contract_id,
            constants.binding_parameter,
            constants.input_parameter,
            constants.release_parameter,
        ):
            # Parameter names are interpolated behind an ARN prefix in the policy
            # file; the binding names are bare literals. Either spelling is exact.
            assert f'"{literal}"' in sources or f'{literal}"' in sources, literal

    def test_the_two_actors_share_no_compiled_value(self) -> None:
        acquisition = pv.constants_for(pv.ProductionActor.ACQUISITION)
        build = pv.constants_for(pv.ProductionActor.BUILD)
        for name in (
            "permission_set",
            "launcher_permission_set",
            "task_role_name",
            "task_family",
            "profile",
            "profile_field",
            "binding_kind",
            "binding_contract_id",
            "binding_env_var",
            "binding_parameter",
            "input_contract_id",
            "input_parameter",
            "release_parameter",
            "identity_field",
        ):
            assert getattr(acquisition, name) != getattr(build, name), name

    def test_the_production_contracts_are_not_the_qualification_contracts(self) -> None:
        for actor in ACTORS:
            constants = pv.constants_for(actor)
            assert constants.binding_kind != rb.RUNTIME_BINDING_KIND
            assert constants.binding_kind != rb.ASSESSMENT_RUNTIME_BINDING_KIND
            assert constants.binding_contract_id != rb.RUNTIME_BINDING_CONTRACT_ID
            assert constants.binding_contract_id != rb.ASSESSMENT_RUNTIME_BINDING_CONTRACT_ID
            assert constants.binding_env_var != rb.RUNTIME_BINDING_ENV_VAR
            assert constants.binding_env_var != rb.ASSESSMENT_RUNTIME_BINDING_ENV_VAR

    def test_constants_for_refuses_a_bare_string(self) -> None:
        with pytest.raises(TypeError):
            pv.constants_for("acquisition")


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class TestParsing:
    @pytest.mark.parametrize("actor", ACTORS, ids=lambda a: a.value)
    def test_a_valid_document_yields_the_binding_and_hides_its_values(
        self, actor: pv.ProductionActor
    ) -> None:
        binding = pb.parse_production_runtime_binding(binding_document(actor), actor=actor)
        assert binding.actor is actor
        assert binding.target_account_id == ACCOUNT
        assert binding.licensed_bucket_name == BUCKET
        assert binding.profile == pv.constants_for(actor).profile
        rendered = repr(binding)
        for canary in CANARIES:
            assert canary not in rendered

    @pytest.mark.parametrize("actor", ACTORS, ids=lambda a: a.value)
    def test_the_other_actors_document_is_refused(self, actor: pv.ProductionActor) -> None:
        other = (
            pv.ProductionActor.BUILD
            if actor is pv.ProductionActor.ACQUISITION
            else pv.ProductionActor.ACQUISITION
        )
        with pytest.raises(rb.RuntimeBindingError) as info:
            pb.parse_production_runtime_binding(binding_document(other), actor=actor)
        # The profile field name differs, so the field-set clause fires first.
        assert info.value.defect in {
            rb.RuntimeBindingDefect.FIELD_UNKNOWN,
            rb.RuntimeBindingDefect.FIELD_MISSING,
        }

    def test_a_qualification_binding_is_refused_by_the_acquisition_loader(self) -> None:
        document = {
            "schema_version": rb.RUNTIME_BINDING_SCHEMA_VERSION,
            "binding_kind": rb.RUNTIME_BINDING_KIND,
            "contract_id": rb.RUNTIME_BINDING_CONTRACT_ID,
            "aws_partition": "aws",
            "aws_region": "us-east-1",
            "target_account_id": ACCOUNT,
            "acquisition_profile": rb.EXPECTED_ACQUISITION_PROFILE,
            "licensed_bucket_name": BUCKET,
            "provenance": binding_document(pv.ProductionActor.ACQUISITION)["provenance"],
        }
        with pytest.raises(rb.RuntimeBindingError) as info:
            pb.parse_production_runtime_binding(document, actor=pv.ProductionActor.ACQUISITION)
        assert info.value.defect is rb.RuntimeBindingDefect.BINDING_KIND_UNKNOWN

    @pytest.mark.parametrize(
        ("overrides", "defect"),
        [
            ({"schema_version": 2}, rb.RuntimeBindingDefect.SCHEMA_VERSION_UNKNOWN),
            ({"schema_version": "1"}, rb.RuntimeBindingDefect.FIELD_MALFORMED),
            ({"binding_kind": "other"}, rb.RuntimeBindingDefect.BINDING_KIND_UNKNOWN),
            ({"contract_id": "other/v1"}, rb.RuntimeBindingDefect.CONTRACT_ID_UNKNOWN),
            ({"aws_partition": "aws-cn"}, rb.RuntimeBindingDefect.PARTITION_UNEXPECTED),
            ({"aws_region": "us-west-2"}, rb.RuntimeBindingDefect.REGION_UNEXPECTED),
            ({"acquisition_profile": "default"}, rb.RuntimeBindingDefect.PROFILE_UNEXPECTED),
            ({"target_account_id": "12345"}, rb.RuntimeBindingDefect.ACCOUNT_MALFORMED),
            ({"target_account_id": 123456789012}, rb.RuntimeBindingDefect.FIELD_MALFORMED),
            ({"licensed_bucket_name": "Bad_Bucket"}, rb.RuntimeBindingDefect.BUCKET_NAME_MALFORMED),
            ({"provenance": {}}, rb.RuntimeBindingDefect.FIELD_MISSING),
            ({"provenance": "x"}, rb.RuntimeBindingDefect.PROVENANCE_MALFORMED),
            ({"extra": 1}, rb.RuntimeBindingDefect.FIELD_UNKNOWN),
        ],
        ids=lambda value: str(value)[:40],
    )
    def test_each_clause_refuses_with_its_own_defect(
        self, overrides: dict[str, Any], defect: rb.RuntimeBindingDefect
    ) -> None:
        with pytest.raises(rb.RuntimeBindingError) as info:
            pb.parse_production_runtime_binding(
                binding_document(pv.ProductionActor.ACQUISITION, **overrides),
                actor=pv.ProductionActor.ACQUISITION,
            )
        assert info.value.defect is defect
        for canary in CANARIES:
            assert canary not in str(info.value) and canary not in repr(info.value)

    def test_a_missing_field_is_refused(self) -> None:
        document = binding_document(pv.ProductionActor.BUILD)
        del document["licensed_bucket_name"]
        with pytest.raises(rb.RuntimeBindingError) as info:
            pb.parse_production_runtime_binding(document, actor=pv.ProductionActor.BUILD)
        assert info.value.defect is rb.RuntimeBindingDefect.FIELD_MISSING

    def test_a_non_object_is_refused(self) -> None:
        with pytest.raises(rb.RuntimeBindingError) as info:
            pb.parse_production_runtime_binding(["x"], actor=pv.ProductionActor.BUILD)
        assert info.value.defect is rb.RuntimeBindingDefect.DOCUMENT_MALFORMED


# ---------------------------------------------------------------------------
# Delivery one: the human's private file, under the accepted reader's rules
# ---------------------------------------------------------------------------


class TestHumanDelivery:
    def _load(
        self,
        tmp_path: Path,
        actor: pv.ProductionActor,
        *,
        raw: bytes | None = None,
        security: rb.FileSecurity | None = None,
        path_override: str | None = None,
    ) -> pb.ProductionRuntimeBinding:
        root = tmp_path / "KalpaMani" / "private"
        root.mkdir(parents=True, exist_ok=True)
        target = root / "binding.json"
        target.write_bytes(json.dumps(binding_document(actor)).encode() if raw is None else raw)
        env = {pv.constants_for(actor).binding_env_var: path_override or str(target)}
        settled = security or _security()
        return pb.load_human_runtime_binding(
            actor,
            environment=env.get,
            root_source=lambda: root,
            security_of=lambda _path: settled,
        )

    @pytest.mark.parametrize("actor", ACTORS, ids=lambda a: a.value)
    def test_a_private_file_loads(self, tmp_path: Path, actor: pv.ProductionActor) -> None:
        assert self._load(tmp_path, actor).actor is actor

    def test_the_variable_is_the_actors_own(self, tmp_path: Path) -> None:
        with pytest.raises(rb.RuntimeBindingError) as info:
            pb.load_human_runtime_binding(
                pv.ProductionActor.BUILD,
                environment={
                    pv.constants_for(pv.ProductionActor.ACQUISITION).binding_env_var: "x"
                }.get,
                root_source=lambda: tmp_path,
            )
        assert info.value.defect is rb.RuntimeBindingDefect.ENVIRONMENT_UNSET

    def test_a_file_outside_the_private_root_is_refused_unread(self, tmp_path: Path) -> None:
        outside = tmp_path / "elsewhere.json"
        outside.write_bytes(b"never opened")
        with pytest.raises(rb.RuntimeBindingError) as info:
            self._load(tmp_path, pv.ProductionActor.ACQUISITION, path_override=str(outside))
        assert info.value.defect is rb.RuntimeBindingDefect.PATH_OUTSIDE_PRIVATE_ROOT

    def test_a_file_another_principal_can_write_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(rb.RuntimeBindingError) as info:
            self._load(
                tmp_path,
                pv.ProductionActor.ACQUISITION,
                security=_security(allow_principals=(CURRENT, OTHER_USER)),
            )
        assert info.value.defect is rb.RuntimeBindingDefect.ACL_NOT_EXCLUSIVE

    def test_a_duplicate_key_is_refused(self, tmp_path: Path) -> None:
        raw = json.dumps(binding_document(pv.ProductionActor.BUILD))
        raw = raw[:-1] + ', "licensed_bucket_name": "other-bucket-name"}'
        with pytest.raises(rb.RuntimeBindingError) as info:
            self._load(tmp_path, pv.ProductionActor.BUILD, raw=raw.encode())
        assert info.value.defect is rb.RuntimeBindingDefect.DUPLICATE_KEY

    def test_the_accepted_reader_is_the_one_used(self) -> None:
        source = (
            PROJECT_ROOT / "src" / "kalpamani" / "data" / "production" / "sharadar" / "bindings.py"
        ).read_text(encoding="utf-8")
        assert "read_private_document(" in source
        assert "read_bytes(" not in source and "open(" not in source


# ---------------------------------------------------------------------------
# Delivery two: the task's parameter
# ---------------------------------------------------------------------------


class TestTaskDelivery:
    @pytest.mark.parametrize("actor", ACTORS, ids=lambda a: a.value)
    def test_the_compiled_parameter_is_the_only_one_read(self, actor: pv.ProductionActor) -> None:
        name = pv.constants_for(actor).binding_parameter
        reader = _Reader({name: json.dumps(binding_document(actor)).encode()})
        binding = pb.load_task_runtime_binding(actor, reader=reader)
        assert binding.actor is actor and reader.reads == [name]

    def test_a_reader_failure_is_one_closed_defect(self) -> None:
        reader = _Reader({}, raising=RuntimeError("backend message with " + BUCKET))
        with pytest.raises(rb.RuntimeBindingError) as info:
            pb.load_task_runtime_binding(pv.ProductionActor.ACQUISITION, reader=reader)
        assert info.value.defect is rb.RuntimeBindingDefect.FILE_UNREADABLE
        assert BUCKET not in str(info.value)

    def test_an_oversize_value_is_refused_before_parsing(self) -> None:
        raw = b"{" + b" " * pv.MAX_BINDING_PARAMETER_BYTES + b"}"
        with pytest.raises(rb.RuntimeBindingError) as info:
            pb.decode_parameter_document(raw, max_bytes=pv.MAX_BINDING_PARAMETER_BYTES)
        assert info.value.defect is rb.RuntimeBindingDefect.FILE_TOO_LARGE

    @pytest.mark.parametrize(
        ("raw", "defect"),
        [
            (b"", rb.RuntimeBindingDefect.FILE_EMPTY),
            (b"\xef\xbb\xbf{}", rb.RuntimeBindingDefect.ENCODING_INVALID),
            (b"\xff\xfe", rb.RuntimeBindingDefect.ENCODING_INVALID),
            (b"{", rb.RuntimeBindingDefect.DOCUMENT_MALFORMED),
            (b'{"a":1,"a":2}', rb.RuntimeBindingDefect.DUPLICATE_KEY),
            ("x", rb.RuntimeBindingDefect.FILE_UNREADABLE),
        ],
    )
    def test_decoding_defects(self, raw: object, defect: rb.RuntimeBindingDefect) -> None:
        with pytest.raises(rb.RuntimeBindingError) as info:
            pb.decode_parameter_document(raw, max_bytes=4096)
        assert info.value.defect is defect


# ---------------------------------------------------------------------------
# The identity gate: three shapes, exact, and the binding as input
# ---------------------------------------------------------------------------


def _binding(actor: pv.ProductionActor) -> pb.ProductionRuntimeBinding:
    return pb.parse_production_runtime_binding(binding_document(actor), actor=actor)


class TestIdentityShapes:
    def test_the_task_shape_parses_and_never_renders(self) -> None:
        parsed = pi.parse_assumed_role_arn(task_identity_arn(pv.ProductionActor.ACQUISITION))
        assert parsed is not None
        assert parsed.role_name == pv.constants_for(pv.ProductionActor.ACQUISITION).task_role_name
        assert parsed.session_name == TASK_ID
        assert ACCOUNT not in repr(parsed) and TASK_ID not in repr(parsed)

    @pytest.mark.parametrize(
        "arn",
        [
            None,
            "",
            f"arn:aws:iam::{ACCOUNT}:role/kalpamani-production-acquire-task",
            f"arn:aws:sts::{ACCOUNT}:federated-user/x",
            f"arn:aws-cn:sts::{ACCOUNT}:assumed-role/x/y",
            f"arn:aws:sts:us-east-1:{ACCOUNT}:assumed-role/x/y",
            "arn:aws:sts::12345:assumed-role/x/y",
            f"arn:aws:sts::{ACCOUNT}:assumed-role/x/y/z",
            f"arn:aws:sts::{ACCOUNT}:assumed-role//y",
            f"arn:aws:sts::{ACCOUNT}:assumed-role/x/",
        ],
    )
    def test_everything_else_fails_closed(self, arn: object) -> None:
        assert pi.parse_assumed_role_arn(arn) is None

    @pytest.mark.parametrize("actor", ACTORS, ids=lambda a: a.value)
    def test_each_path_matches_only_its_own_role(self, actor: pv.ProductionActor) -> None:
        constants = pv.constants_for(actor)
        human = f"AWSReservedSSO_{constants.permission_set}_0123abcd"
        launcher = f"AWSReservedSSO_{constants.launcher_permission_set}_0123abcd"
        task = constants.task_role_name
        table = {
            pv.IdentityPath.HUMAN: human,
            pv.IdentityPath.LAUNCHER: launcher,
            pv.IdentityPath.TASK: task,
        }
        for path, role in table.items():
            for other_path in pv.IdentityPath:
                assert pi.role_matches_path(actor, other_path, role) is (other_path is path), (
                    path,
                    other_path,
                )

    def test_the_generated_suffix_grammar_is_the_qualification_gates(self) -> None:
        # Uppercase, an underscore and an empty suffix are refused; hex is admitted.
        assert pi.generated_role_suffix("X", "AWSReservedSSO_X_abc123") == "abc123"
        assert pi.generated_role_suffix("X", "AWSReservedSSO_X_ABC") is None
        assert pi.generated_role_suffix("X", "AWSReservedSSO_X_") is None
        assert pi.generated_role_suffix("X", "AWSReservedSSO_X_ab_cd") is None
        assert pi.generated_role_suffix("X", "AWSReservedSSO_XY_abc") is None

    def test_a_qualification_role_matches_no_production_path(self) -> None:
        for role in (
            "AWSReservedSSO_KalpaManiQualificationAcquire_0123abcd",
            "AWSReservedSSO_KalpaManiQualificationAssessment_0123abcd",
            "kalpamani-research-task",
        ):
            for actor in ACTORS:
                for path in pv.IdentityPath:
                    assert pi.role_matches_path(actor, path, role) is False


class TestTheGate:
    @pytest.mark.parametrize("actor", ACTORS, ids=lambda a: a.value)
    def test_a_task_running_as_its_own_role_is_proven(self, actor: pv.ProductionActor) -> None:
        proof = pi.production_identity_refusal(
            actor,
            path=pv.IdentityPath.TASK,
            binding=_binding(actor),
            caller_identity=lambda: caller_identity(task_identity_arn(actor)),
        )
        assert isinstance(proof, pi.ProvenIdentity)
        assert proof.task_id == TASK_ID and TASK_ID not in repr(proof)

    @pytest.mark.parametrize("actor", ACTORS, ids=lambda a: a.value)
    def test_a_human_and_a_launcher_are_proven_under_their_own_paths(
        self, actor: pv.ProductionActor
    ) -> None:
        for path, arn in (
            (pv.IdentityPath.HUMAN, human_identity_arn(actor)),
            (pv.IdentityPath.LAUNCHER, launcher_identity_arn(actor)),
        ):
            proof = pi.production_identity_refusal(
                actor,
                path=path,
                binding=_binding(actor),
                caller_identity=functools.partial(caller_identity, arn),
            )
            assert isinstance(proof, pi.ProvenIdentity) and proof.task_id is None

    @pytest.mark.parametrize(
        ("actor", "path", "arn"),
        [
            # The other actor's task role.
            (
                pv.ProductionActor.ACQUISITION,
                pv.IdentityPath.TASK,
                task_identity_arn(pv.ProductionActor.BUILD),
            ),
            (
                pv.ProductionActor.BUILD,
                pv.IdentityPath.TASK,
                task_identity_arn(pv.ProductionActor.ACQUISITION),
            ),
            # The right actor under the wrong path.
            (
                pv.ProductionActor.ACQUISITION,
                pv.IdentityPath.HUMAN,
                task_identity_arn(pv.ProductionActor.ACQUISITION),
            ),
            (
                pv.ProductionActor.ACQUISITION,
                pv.IdentityPath.TASK,
                human_identity_arn(pv.ProductionActor.ACQUISITION),
            ),
            (
                pv.ProductionActor.ACQUISITION,
                pv.IdentityPath.HUMAN,
                launcher_identity_arn(pv.ProductionActor.ACQUISITION),
            ),
            (
                pv.ProductionActor.ACQUISITION,
                pv.IdentityPath.LAUNCHER,
                human_identity_arn(pv.ProductionActor.ACQUISITION),
            ),
            # A qualification actor, the foundation role, a default chain.
            (
                pv.ProductionActor.ACQUISITION,
                pv.IdentityPath.HUMAN,
                f"arn:aws:sts::{ACCOUNT}:assumed-role/AWSReservedSSO_KalpaManiQualificationAcquire_0123abcd/op",
            ),
            (
                pv.ProductionActor.BUILD,
                pv.IdentityPath.TASK,
                f"arn:aws:sts::{ACCOUNT}:assumed-role/kalpamani-research-task/{TASK_ID}",
            ),
            (
                pv.ProductionActor.BUILD,
                pv.IdentityPath.HUMAN,
                f"arn:aws:iam::{ACCOUNT}:user/default",
            ),
        ],
    )
    def test_every_other_principal_refuses_value_free(
        self, actor: pv.ProductionActor, path: pv.IdentityPath, arn: str
    ) -> None:
        reason = pi.production_identity_refusal(
            actor, path=path, binding=_binding(actor), caller_identity=lambda: caller_identity(arn)
        )
        assert isinstance(reason, str)
        for canary in CANARIES:
            assert canary not in reason
        assert "AWSReservedSSO" not in reason and "arn:" not in reason

    def test_the_account_is_compared_to_the_binding(self) -> None:
        actor = pv.ProductionActor.ACQUISITION
        reason = pi.production_identity_refusal(
            actor,
            path=pv.IdentityPath.TASK,
            binding=_binding(actor),
            caller_identity=lambda: caller_identity(
                task_identity_arn(actor), account=OTHER_ACCOUNT
            ),
        )
        assert reason == "the authenticated account does not match the runtime binding"

    def test_an_arn_account_disagreeing_with_the_reported_account_refuses(self) -> None:
        actor = pv.ProductionActor.ACQUISITION
        arn = task_identity_arn(actor).replace(ACCOUNT, OTHER_ACCOUNT)
        reason = pi.production_identity_refusal(
            actor,
            path=pv.IdentityPath.TASK,
            binding=_binding(actor),
            caller_identity=lambda: caller_identity(arn),
        )
        assert isinstance(reason, str) and "not a usable" not in reason

    def test_a_task_session_that_is_not_a_task_id_refuses(self) -> None:
        actor = pv.ProductionActor.BUILD
        role = pv.constants_for(actor).task_role_name
        arn = f"arn:aws:sts::{ACCOUNT}:assumed-role/{role}/not-a-task-id"
        reason = pi.production_identity_refusal(
            actor,
            path=pv.IdentityPath.TASK,
            binding=_binding(actor),
            caller_identity=lambda: caller_identity(arn),
        )
        assert reason == "the task-role session is not named by a well-formed task id"

    def test_the_binding_is_checked_before_the_identity_call(self) -> None:
        calls: list[int] = []

        def identity() -> dict[str, str]:
            calls.append(1)
            return caller_identity(task_identity_arn(pv.ProductionActor.ACQUISITION))

        reason = pi.production_identity_refusal(
            pv.ProductionActor.ACQUISITION,
            path=pv.IdentityPath.TASK,
            binding=_binding(pv.ProductionActor.BUILD),
            caller_identity=identity,
        )
        assert isinstance(reason, str) and calls == []

    def test_a_raising_identity_call_refuses_without_its_message(self) -> None:
        def identity() -> dict[str, str]:
            raise RuntimeError("secret backend text " + ACCOUNT)

        actor = pv.ProductionActor.ACQUISITION
        reason = pi.production_identity_refusal(
            actor, path=pv.IdentityPath.TASK, binding=_binding(actor), caller_identity=identity
        )
        assert reason == "could not resolve an authenticated AWS identity"

    def test_the_qualification_gates_own_grammar_is_unchanged(self) -> None:
        source = (PROJECT_ROOT / "scripts" / "aws_foundation_verify.py").read_text(encoding="utf-8")
        assert re.search(r'GENERATED_SUFFIX_RE = re\.compile\(r"\[0-9a-f\]\{1,32\}"\)', source)
        assert 'GENERATED_ROLE_PREFIX = "AWSReservedSSO_"' in source
        assert pi.GENERATED_SUFFIX_RE.pattern == r"[0-9a-f]{1,32}"
