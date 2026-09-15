"""The ADR-0050 declaration, parsed (`production_deletion_rehearsal.tf`): inert
under the committed defaults, gated three ways, the task as the actual deletion role, the
deletion role's delta three reads and nothing else, the launcher with no S3 action, the
one assignment behind stage b. A structural rule over the HCL, beside the mock-provider
runs in tests/terraform/production.tftest.hcl (executed only in an external copy)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from test_production_infrastructure import (
    GUARD,
    INFRA,
    PRODUCTION_FILES,
    Model,
    Statement,
    _denied,
    _granted,
    _has_condition,
    build_model,
)

from kalpamani.data.production.sharadar import deletion_rehearsal as dr
from kalpamani.data.production.sharadar import deletion_rehearsal_task as dt

pytestmark = pytest.mark.unit

REHEARSAL_TF = INFRA / "production_deletion_rehearsal.tf"
OPEN_GATE = "local.deletion_rehearsal_open ? [1] : []"


@pytest.fixture(scope="module")
def sources() -> dict[str, str]:
    files = {name: (INFRA / name).read_text(encoding="utf-8") for name in PRODUCTION_FILES}
    files["production_deletion_rehearsal.tf"] = REHEARSAL_TF.read_text(encoding="utf-8")
    files["storage.tf"] = (INFRA / "storage.tf").read_text(encoding="utf-8")
    files["iam.tf"] = (INFRA / "iam.tf").read_text(encoding="utf-8")
    return files


@pytest.fixture(scope="module")
def model(sources: dict[str, str]) -> Model:
    return build_model(sources)


def _rehearsal_resources(model: Model) -> list[Any]:
    return [b for b in model.by_file["production_deletion_rehearsal.tf"] if b.type == "resource"]


class TestInertByDefault:
    def test_the_variable_defaults_to_false_and_the_local_needs_all_three(
        self, model: Model
    ) -> None:
        variable = model.variables["deletion_rehearsal_open"]
        assert variable.attributes.get("type", "").strip() == "bool"
        assert variable.attributes.get("default", "").strip() == "false"
        gate = model.raw_locals["deletion_rehearsal_open"]
        assert "local.production_stage_a" in gate
        assert "var.deletion_rehearsal_open" in gate
        assert 'contains(keys(var.production_image_digests), "deletion_rehearsal")' in gate
        assert model.raw_locals["deletion_rehearsal_count"].strip() == (
            "local.deletion_rehearsal_open ? 1 : 0"
        )
        assert model.raw_locals["deletion_rehearsal_assignment_count"].strip() == (
            "local.deletion_rehearsal_open && local.production_stage_b ? 1 : 0"
        )

    def test_every_rehearsal_resource_is_count_gated(self, model: Model) -> None:
        resources = _rehearsal_resources(model)
        kinds = sorted(f"{b.labels[0]}.{b.labels[1]}" for b in resources)
        assert kinds == [
            "aws_ecs_task_definition.deletion_rehearsal",
            "aws_iam_policy.deletion_rehearsal_launcher",
            "aws_iam_role_policy.deletion_rehearsal_bootstrap",
            "aws_ssm_parameter.deletion_rehearsal_binding",
            "aws_ssoadmin_account_assignment.deletion_rehearsal_launcher",
            "aws_ssoadmin_customer_managed_policy_attachment.deletion_rehearsal_launcher",
            "aws_ssoadmin_permission_set.deletion_rehearsal_launcher",
        ]
        for block in resources:
            count = block.attributes.get("count", "").strip()
            if block.labels[0] == "aws_ssoadmin_account_assignment":
                assert count == "local.deletion_rehearsal_assignment_count", block.labels
            else:
                assert count == "local.deletion_rehearsal_count", block.labels
        # No policy attachment resource: the deletion role's delta is one inline policy,
        # and the ADR-0036 attachment guard stays at its four.
        assert not any(b.labels[0] == "aws_iam_role_policy_attachment" for b in resources)

    def test_the_key_policy_statements_are_gated_on_the_same_local(
        self, model: Model, sources: dict[str, str]
    ) -> None:
        key = model.documents["production_task_bindings_key"]
        rehearsal = [s for s in key if s.sid.startswith("Deletion")]
        assert {s.sid for s in rehearsal} == {
            "DeletionRoleDecryptsTheRehearsalParameters",
            "DeletionRehearsalLauncherGeneratesTheInputAndReleaseDataKeys",
        }
        for s in rehearsal:
            assert s.dynamic_gate == OPEN_GATE
            assert s.effect == "Allow"
            assert _has_condition(s, "StringEquals", "kms:ViaService")
            assert _has_condition(s, "StringEquals", "kms:EncryptionContext:PARAMETER_ARN")
        decrypt = next(s for s in rehearsal if s.actions == ("kms:Decrypt",))
        assert decrypt.principals[0][0] == "AWS"
        generate = next(s for s in rehearsal if s.actions == ("kms:GenerateDataKey",))
        assert _has_condition(generate, "ArnLike", "aws:PrincipalArn")
        # References resolve to nothing in the model; the source names them exactly.
        bindings = sources["production_bindings.tf"]
        assert "identifiers = [aws_iam_role.licensed_data_deletion.arn]" in bindings
        assert '"${local.production_sso_role_path}${local.deletion_rehearsal_set}_*"' in bindings

    def test_no_live_literal(self, sources: dict[str, str]) -> None:
        text = sources["production_deletion_rehearsal.tf"]
        assert re.search(r"\b[0-9]{12}\b", text) is None
        assert "arn:aws:iam::" not in text.replace("arn:aws:iam::${", "")


class TestTheTaskDefinition:
    def test_it_runs_as_the_actual_deletion_role_under_the_foundation_execution_role(
        self, model: Model
    ) -> None:
        task = model.resources[("aws_ecs_task_definition", "deletion_rehearsal")]
        attributes = task.attributes
        assert attributes["task_role_arn"].strip() == "aws_iam_role.licensed_data_deletion.arn"
        assert attributes["execution_role_arn"].strip() == "aws_iam_role.task_execution.arn"
        assert attributes["family"].strip() == "local.deletion_rehearsal_family"
        assert model.raw_locals["deletion_rehearsal_family"].strip() == f'"{dr.REHEARSAL_FAMILY}"'
        assert model.raw_locals["deletion_rehearsal_entry"].strip() == f'"{dr.REHEARSAL_ENTRY}"'
        assert model.raw_locals["deletion_rehearsal_container"].strip() == (
            f'"{dr.REHEARSAL_CONTAINER}"'
        )
        assert model.raw_locals["deletion_rehearsal_prefix"].strip() == (
            f'"{dr.REHEARSAL_STREAM_PREFIX}"'
        )
        assert (
            model.raw_locals["deletion_rehearsal_set"]
            .strip()
            .startswith(f'"{dr.REHEARSAL_LAUNCHER_PERMISSION_SET}"')
        )
        assert len(dr.REHEARSAL_LAUNCHER_PERMISSION_SET) <= 32
        # The same shape as the production task; a private task network; no override
        # is possible from the launcher (the compiled request carries none).
        assert attributes["cpu"].strip() == "local.production_task_cpu"
        assert attributes["memory"].strip() == "local.production_task_memory"
        assert attributes["network_mode"].strip() == '"awsvpc"'

    def test_the_container_is_the_rehearsal_entry_logging_under_its_own_prefix(
        self, model: Model
    ) -> None:
        container = model.raw_locals["deletion_rehearsal_container_definition"]
        assert "command   = [local.deletion_rehearsal_entry]" in container
        assert '"awslogs-stream-prefix" = local.deletion_rehearsal_prefix' in container
        assert (
            'lookup(var.production_image_digests, "deletion_rehearsal", "sha256:unset")'
            in container
        )
        assert "readonlyRootFilesystem = true" in container

    def test_the_binding_parameter_carries_the_task_contract(self, model: Model) -> None:
        binding = model.raw_locals["deletion_rehearsal_binding"]
        assert f'binding_kind         = "{dt.REHEARSAL_BINDING_KIND}"' in binding
        assert f'contract_id          = "{dr.REHEARSAL_BINDING_CONTRACT_ID}"' in binding
        assert "deletion_role_name   = aws_iam_role.licensed_data_deletion.name" in binding
        assert "licensed_bucket_name = aws_s3_bucket.licensed.id" in binding
        parameter = model.resources[("aws_ssm_parameter", "deletion_rehearsal_binding")]
        assert parameter.attributes["name"].strip() == f'"{dr.REHEARSAL_BINDING_PARAMETER}"'
        assert parameter.attributes["type"].strip() == '"SecureString"'
        assert parameter.attributes["key_id"].strip() == (
            "aws_kms_key.production_task_bindings[0].arn"
        )
        for name, suffix in (
            ("deletion_rehearsal_binding_parameter_arn", dr.REHEARSAL_BINDING_PARAMETER),
            ("deletion_rehearsal_input_parameter_arn", dr.REHEARSAL_INPUT_PARAMETER),
            ("deletion_rehearsal_release_parameter_arn", dr.REHEARSAL_RELEASE_PARAMETER),
        ):
            assert model.raw_locals[name].strip().endswith(f'{suffix}"')


class TestTheDeletionRolesDelta:
    def test_three_exact_reads_a_scoped_decrypt_and_nothing_else(self, model: Model) -> None:
        bootstrap = model.documents["deletion_rehearsal_bootstrap"]
        assert _granted(bootstrap) == {"ssm:GetParameter", "kms:Decrypt"}
        read = next(s for s in bootstrap if s.actions == ("ssm:GetParameter",))
        assert read.raw_resources.strip() == "local.deletion_rehearsal_task_parameter_arns"
        decrypt = next(s for s in bootstrap if s.actions == ("kms:Decrypt",))
        assert decrypt.dynamic_gate == OPEN_GATE
        assert _has_condition(decrypt, "StringEquals", "kms:ViaService")
        assert _has_condition(decrypt, "StringEquals", "kms:EncryptionContext:PARAMETER_ARN")
        denied = _denied(bootstrap)
        assert {"ssm:PutParameter", "ssm:DeleteParameter", "ssm:GetParametersByPath"} <= denied
        assert {"kms:Encrypt", "kms:GenerateDataKey"} <= denied
        # No S3 action anywhere in the delta: the role's object authority is iam.tf's
        # alone (list and delete; no read, no write), and the delta widens nothing.
        assert not any(a.startswith("s3:") for s in bootstrap for a in s.actions)
        policy = model.resources[("aws_iam_role_policy", "deletion_rehearsal_bootstrap")]
        assert policy.attributes["role"].strip() == "aws_iam_role.licensed_data_deletion.id"

    def test_iam_tf_is_unchanged_in_what_it_grants_the_deletion_role(
        self, sources: dict[str, str]
    ) -> None:
        iam = GUARD.strip_hcl_comments(sources["iam.tf"])
        assert "deletion_rehearsal" not in iam and "iam:PassRole" not in iam
        deletion = iam.split('data "aws_iam_policy_document" "licensed_data_deletion"')[1]
        assert "ssm:" not in deletion.split("\n}\n")[0]


class TestTheLauncher:
    def _launcher(self, model: Model) -> tuple[Statement, ...]:
        return model.documents["deletion_rehearsal_launcher"]

    def test_one_revision_two_passable_roles_and_no_s3_action(self, model: Model) -> None:
        launcher = self._launcher(model)
        run = next(s for s in launcher if s.actions == ("ecs:RunTask",))
        assert run.dynamic_gate == OPEN_GATE
        assert run.raw_resources.strip() == "[aws_ecs_task_definition.deletion_rehearsal[0].arn]"
        assert _has_condition(run, "ArnEquals", "ecs:cluster")
        passes = next(s for s in launcher if s.actions == ("iam:PassRole",) and s.effect == "Allow")
        two_roles = "[aws_iam_role.licensed_data_deletion.arn, aws_iam_role.task_execution.arn]"
        assert passes.raw_resources.strip() == two_roles
        assert _has_condition(
            passes, "StringEquals", "iam:PassedToService", ("ecs-tasks.amazonaws.com",)
        )
        closed = next(s for s in launcher if s.actions == ("iam:PassRole",) and s.effect == "Deny")
        assert closed.raw_not_resources.strip() == two_roles
        granted = _granted(launcher)
        assert not any(a.startswith("s3:") for a in granted)
        assert "s3:*" in _denied(launcher) and "secretsmanager:*" in _denied(launcher)
        assert "sts:AssumeRole" in _denied(launcher)
        assert {"ecs:ExecuteCommand", "ecs:RegisterTaskDefinition"} <= _denied(launcher)
        assert {"ssm:GetParameter", "kms:Decrypt", "kms:Encrypt"} <= _denied(launcher)
        assert granted == {
            "ecs:RunTask",
            "iam:PassRole",
            "ecs:DescribeTasks",
            "ecs:StopTask",
            "ec2:DescribeNetworkInterfaces",
            "ssm:PutParameter",
            "ssm:DeleteParameter",
            "kms:GenerateDataKey",
            "logs:GetLogEvents",
        }

    def test_two_create_only_parameters_and_the_rehearsal_streams(self, model: Model) -> None:
        launcher = self._launcher(model)
        put = next(
            s for s in launcher if s.actions == ("ssm:PutParameter",) and s.effect == "Allow"
        )
        assert put.raw_resources.strip() == "local.deletion_rehearsal_launcher_parameter_arns"
        assert _has_condition(put, "Bool", "ssm:Overwrite", ("false",))
        overwrite = next(
            s for s in launcher if s.actions == ("ssm:PutParameter",) and s.effect == "Deny"
        )
        assert _has_condition(overwrite, "Bool", "ssm:Overwrite", ("true",))
        other = next(s for s in launcher if s.sid == "LauncherWritesNoOtherParameter")
        assert other.raw_not_resources.strip() == "local.deletion_rehearsal_launcher_parameter_arns"
        generate = next(s for s in launcher if s.actions == ("kms:GenerateDataKey",))
        assert generate.dynamic_gate == OPEN_GATE
        assert _has_condition(generate, "StringEquals", "kms:EncryptionContext:PARAMETER_ARN")
        logs = next(s for s in launcher if s.actions == ("logs:GetLogEvents",))
        assert "${local.deletion_rehearsal_prefix}/${local.deletion_rehearsal_container}/*" in (
            logs.raw_resources
        )
        assert "aws_cloudwatch_log_group.research.arn" in logs.raw_resources

    def test_the_permission_set_and_its_assignment(self, model: Model) -> None:
        permission_set = model.resources[
            ("aws_ssoadmin_permission_set", "deletion_rehearsal_launcher")
        ]
        assert permission_set.attributes["name"].strip() == "local.deletion_rehearsal_set"
        assert permission_set.attributes["session_duration"].strip() == (
            "local.production_session_duration"
        )
        reference = model.resources[
            ("aws_ssoadmin_customer_managed_policy_attachment", "deletion_rehearsal_launcher")
        ]
        assert "aws_iam_policy.deletion_rehearsal_launcher[0]" in "".join(
            c.attributes.get("name", "")
            for c in reference.children("customer_managed_policy_reference")
        )
        assignment = model.resources[
            ("aws_ssoadmin_account_assignment", "deletion_rehearsal_launcher")
        ]
        assert assignment.attributes["principal_id"].strip() == "local.production_operator_group_id"
        assert assignment.attributes["target_id"].strip() == "local.production_target_account_id"
        assert "local.production_account_consistent" in "".join(
            p.attributes.get("condition", "")
            for lifecycle in assignment.children("lifecycle")
            for p in lifecycle.children("precondition")
        )


def test_the_tftest_covers_the_closed_default_and_the_open_stages() -> None:
    text = (Path(INFRA).parents[2] / "tests" / "terraform" / "production.tftest.hcl").read_text(
        encoding="utf-8"
    )
    for run in (
        "rehearsal_closed_by_default_at_stage_a_with_its_digest",
        "rehearsal_open_without_its_digest_declares_nothing",
        "rehearsal_open_at_stage_none_declares_nothing",
        "rehearsal_open_at_stage_a_declares_the_task_the_set_and_no_assignment",
        "rehearsal_open_at_stage_b_declares_the_one_assignment",
    ):
        assert f'run "{run}"' in text
    assert "stage none must declare no deletion rehearsal resource" in text
