# Proposed ADR-0050 -- THE DELETION REHEARSAL, DECLARED INERT.
#
# ADR-0049 s.3 implemented the deletion rehearsal offline and named the resources
# the governance decision D-1 would declare; this file declares them, and declares
# them CLOSED. Every resource here is gated on THREE conditions at once:
#
#   production_stage a or b            the ADR-0036 stage gate, as for every
#                                      production resource
#   deletion_rehearsal_open = true     the owner's written acceptance of ADR-0050
#                                      D-1, supplied in the git-ignored .tfvars --
#                                      FALSE BY DEFAULT
#   production_image_digests["deletion_rehearsal"]
#                                      the rehearsal image, pinned by digest -- an
#                                      image that does not exist until an image gate
#                                      builds one
#
# and the one account assignment is additionally gated on stage b. With the
# committed defaults this file declares NOTHING: no task definition, no permission
# set, no policy, no parameter, no key-policy statement and no assignment -- the
# `stage_none`, `rehearsal_closed_*` and `rehearsal_without_a_digest_*` runs of
# tests/terraform/production.tftest.hcl hold that, and so does the structural test.
# Declaring is not applying; opening the variable is a separately authorized apply
# under ADR-0050's own runtime authorization, never a default.
#
# WHAT THE OPEN SETTING WOULD DECLARE, AND NOTHING MORE
#
#   aws_ecs_task_definition.deletion_rehearsal
#       family `kalpamani-deletion-rehearsal`, task role `aws_iam_role.licensed_data_deletion`
#       -- the ACTUAL deletion role, so the rehearsal runs as the identity it rehearses,
#       never as a human and never as a production actor -- the foundation execution
#       role, one container `deletion-rehearsal` whose command is the closed entry
#       `kalpamani-deletion-rehearsal`, on the production task shape, logging under the
#       stream prefix `production-deletion-rehearsal`.
#   aws_iam_role_policy.deletion_rehearsal_bootstrap
#       the ONLY addition to the deletion role: three exact `ssm:GetParameter` reads
#       (its runtime binding, the launcher's input, the launcher's release) and the
#       scoped `kms:Decrypt` those reads need through Parameter Store. No S3 action is
#       added or widened: the role keeps exactly the list/delete authority iam.tf gives
#       it, and still cannot read or write an object.
#   aws_ssm_parameter.deletion_rehearsal_binding
#       the deletion rehearsal runtime binding (`kalpamani-deletion-runtime-binding/v1`):
#       account, region, bucket, the deletion role's exact name, provenance.
#   aws_iam_policy.deletion_rehearsal_launcher + aws_ssoadmin_permission_set.deletion_rehearsal_launcher
#       `KalpaManiDeletionRehearse`: RunTask of exactly the rehearsal revision in the one
#       cluster; PassRole of exactly the deletion role and the execution role to ECS
#       tasks; DescribeTasks/StopTask in the one cluster; DescribeNetworkInterfaces;
#       create-only PutParameter and DeleteParameter on exactly the rehearsal input and
#       release parameters, with the scoped GenerateDataKey; GetLogEvents on exactly the
#       rehearsal container's streams (the collector, ADR-0049 s.2); ExecuteCommand and
#       every parameter read explicitly denied. The launcher holds no S3 action at all.
#   aws_ssoadmin_account_assignment.deletion_rehearsal_launcher   (stage b only)
#       the governed operator group, the one account.
#
# The two key-policy statements the deletion role and the launcher need are dynamic
# statements in production_bindings.tf, gated on the same `local.deletion_rehearsal_open`.
#
# WHAT IT DOES NOT DO. It grants no human the deletion role (no human can assume it;
# the launcher passes it to ECS and that is all), it widens no production actor, it
# creates no general deletion utility, and it targets nothing: the target is the one
# synthetic object the rehearsal statement names, bound by the R-4 record, enforced in
# code (the task refuses any bucket but the bound one; the engine issues at most one
# read, one list of MaxKeys=1 and one delete of the exact key). IAM cannot express
# "this one key" for a delete, and the ADR says so.

locals {
  deletion_rehearsal_family    = "kalpamani-deletion-rehearsal"
  deletion_rehearsal_entry     = "kalpamani-deletion-rehearsal"
  deletion_rehearsal_container = "deletion-rehearsal"
  deletion_rehearsal_prefix    = "production-deletion-rehearsal"
  deletion_rehearsal_set       = "KalpaManiDeletionRehearse" # 25

  # OPEN only when the owner accepted D-1 (the variable), the stage gate is passed
  # and the rehearsal image is pinned. Never at stage none; never by default.
  deletion_rehearsal_open  = local.production_stage_a && var.deletion_rehearsal_open && contains(keys(var.production_image_digests), "deletion_rehearsal")
  deletion_rehearsal_count = local.deletion_rehearsal_open ? 1 : 0
  # The assignment: open AND stage b -- the same R-3 gate every assignment sits behind.
  deletion_rehearsal_assignment_count = local.deletion_rehearsal_open && local.production_stage_b ? 1 : 0

  deletion_rehearsal_binding_parameter_arn = "${local.production_parameter_arn_prefix}/kalpamani/production/deletion/runtime-binding"
  deletion_rehearsal_input_parameter_arn   = "${local.production_parameter_arn_prefix}/kalpamani/production/deletion/input"
  deletion_rehearsal_release_parameter_arn = "${local.production_parameter_arn_prefix}/kalpamani/production/deletion/release"

  deletion_rehearsal_task_parameter_arns = [
    local.deletion_rehearsal_binding_parameter_arn,
    local.deletion_rehearsal_input_parameter_arn,
    local.deletion_rehearsal_release_parameter_arn,
  ]

  deletion_rehearsal_launcher_parameter_arns = [
    local.deletion_rehearsal_input_parameter_arn,
    local.deletion_rehearsal_release_parameter_arn,
  ]

  deletion_rehearsal_binding = {
    schema_version       = 1
    binding_kind         = "kalpamani-deletion-rehearsal-runtime"
    contract_id          = "kalpamani-deletion-runtime-binding/v1"
    aws_partition        = "aws"
    aws_region           = var.aws_region
    target_account_id    = local.production_target_account_id
    licensed_bucket_name = aws_s3_bucket.licensed.id
    deletion_role_name   = aws_iam_role.licensed_data_deletion.name
    provenance           = var.production_binding_provenance
  }

  deletion_rehearsal_container_definition = {
    name      = local.deletion_rehearsal_container
    image     = "${local.production_image_repository}@${lookup(var.production_image_digests, "deletion_rehearsal", "sha256:unset")}"
    essential = true
    command   = [local.deletion_rehearsal_entry]
    cpu       = 1024
    memory    = 2048
    user      = "10001:10001"
    linuxParameters = {
      initProcessEnabled = true
      tmpfs = [{
        containerPath = "/work"
        size          = 256
        mountOptions  = ["rw", "noexec", "nosuid"]
      }]
    }
    readonlyRootFilesystem = true
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.research.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = local.deletion_rehearsal_prefix
      }
    }
  }
}

# ---------------------------------------------------------------------------
# The task definition: the deletion role's, and only the rehearsal entry
# ---------------------------------------------------------------------------

resource "aws_ecs_task_definition" "deletion_rehearsal" {
  count = local.deletion_rehearsal_count

  family                   = local.deletion_rehearsal_family
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = local.production_task_cpu
  memory                   = local.production_task_memory
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.licensed_data_deletion.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([local.deletion_rehearsal_container_definition])

  tags = {
    Purpose = "deletion-rehearsal"
  }
}

# ---------------------------------------------------------------------------
# The deletion role's bootstrap delta: three exact reads, scoped decrypt, no writes
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "deletion_rehearsal_bootstrap" {
  statement {
    sid       = "ReadTheRehearsalsThreeParameters"
    effect    = "Allow"
    actions   = ["ssm:GetParameter"]
    resources = local.deletion_rehearsal_task_parameter_arns
  }

  dynamic "statement" {
    for_each = local.deletion_rehearsal_open ? [1] : []

    content {
      sid       = "DecryptThoseParametersThroughParameterStoreOnly"
      effect    = "Allow"
      actions   = ["kms:Decrypt"]
      resources = [aws_kms_key.production_task_bindings[0].arn]

      condition {
        test     = "StringEquals"
        variable = "kms:EncryptionContext:PARAMETER_ARN"
        values   = local.deletion_rehearsal_task_parameter_arns
      }

      condition {
        test     = "StringEquals"
        variable = "kms:ViaService"
        values   = [local.production_ssm_via_service]
      }
    }
  }

  statement {
    sid    = "TaskNeverEnumeratesParameters"
    effect = "Deny"
    actions = [
      "ssm:GetParameters",
      "ssm:GetParametersByPath",
      "ssm:DescribeParameters",
      "ssm:GetParameterHistory",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "TaskNeverWritesAParameterOrEncrypts"
    effect = "Deny"
    actions = [
      "ssm:PutParameter",
      "ssm:DeleteParameter",
      "ssm:DeleteParameters",
      "ssm:LabelParameterVersion",
      "kms:Encrypt",
      "kms:GenerateDataKey",
      "kms:GenerateDataKeyWithoutPlaintext",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "deletion_rehearsal_bootstrap" {
  count = local.deletion_rehearsal_count

  name   = "${var.name_prefix}-deletion-rehearsal-bootstrap"
  role   = aws_iam_role.licensed_data_deletion.id
  policy = data.aws_iam_policy_document.deletion_rehearsal_bootstrap.json
}

# ---------------------------------------------------------------------------
# The runtime binding the rehearsal task reads
# ---------------------------------------------------------------------------

resource "aws_ssm_parameter" "deletion_rehearsal_binding" {
  count = local.deletion_rehearsal_count

  name        = "/kalpamani/production/deletion/runtime-binding"
  description = "Proposed ADR-0050 deletion rehearsal runtime binding. Read by the deletion role only, inside the rehearsal task."
  type        = "SecureString"
  tier        = "Standard"
  key_id      = aws_kms_key.production_task_bindings[0].arn
  value       = jsonencode(local.deletion_rehearsal_binding)

  tags = {
    Purpose = "deletion-rehearsal"
  }
}

# ---------------------------------------------------------------------------
# The launcher: one revision, two passable roles, two create-only parameters,
# the rehearsal container's streams, and no S3 action at all
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "deletion_rehearsal_launcher" {
  dynamic "statement" {
    for_each = local.deletion_rehearsal_open ? [1] : []

    content {
      sid       = "RunExactlyTheRehearsalRevisionInTheOneCluster"
      effect    = "Allow"
      actions   = ["ecs:RunTask"]
      resources = [aws_ecs_task_definition.deletion_rehearsal[0].arn]

      condition {
        test     = "ArnEquals"
        variable = "ecs:cluster"
        values   = [aws_ecs_cluster.research.arn]
      }
    }
  }

  statement {
    sid       = "PassExactlyTheDeletionRoleAndTheExecutionRoleToEcsTasks"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.licensed_data_deletion.arn, aws_iam_role.task_execution.arn]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }

  statement {
    sid           = "PassNoOtherRole"
    effect        = "Deny"
    actions       = ["iam:PassRole"]
    not_resources = [aws_iam_role.licensed_data_deletion.arn, aws_iam_role.task_execution.arn]
  }

  statement {
    sid       = "ObserveAndStopTasksInTheOneCluster"
    effect    = "Allow"
    actions   = ["ecs:DescribeTasks", "ecs:StopTask"]
    resources = ["*"]

    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [aws_ecs_cluster.research.arn]
    }
  }

  statement {
    sid       = "DescribeTheTasksNetworkInterface"
    effect    = "Allow"
    actions   = ["ec2:DescribeNetworkInterfaces"]
    resources = ["*"]
  }

  statement {
    sid       = "WriteTheRehearsalInputAndReleaseOnce"
    effect    = "Allow"
    actions   = ["ssm:PutParameter"]
    resources = local.deletion_rehearsal_launcher_parameter_arns

    condition {
      test     = "Bool"
      variable = "ssm:Overwrite"
      values   = ["false"]
    }
  }

  statement {
    sid       = "DeleteTheRehearsalInputAndReleaseAfterTheRun"
    effect    = "Allow"
    actions   = ["ssm:DeleteParameter"]
    resources = local.deletion_rehearsal_launcher_parameter_arns
  }

  dynamic "statement" {
    for_each = local.deletion_rehearsal_open ? [1] : []

    content {
      sid       = "GenerateTheirDataKeysThroughParameterStoreOnly"
      effect    = "Allow"
      actions   = ["kms:GenerateDataKey"]
      resources = [aws_kms_key.production_task_bindings[0].arn]

      condition {
        test     = "StringEquals"
        variable = "kms:EncryptionContext:PARAMETER_ARN"
        values   = local.deletion_rehearsal_launcher_parameter_arns
      }

      condition {
        test     = "StringEquals"
        variable = "kms:ViaService"
        values   = [local.production_ssm_via_service]
      }
    }
  }

  # The collector (ADR-0049 s.2): exactly the rehearsal container's streams, read
  # only. Recorded for the probe launchers and not granted there; proposed here for
  # the one launcher whose task's receipt no human role can otherwise reach.
  statement {
    sid       = "ReadTheRehearsalContainersStreams"
    effect    = "Allow"
    actions   = ["logs:GetLogEvents"]
    resources = ["${aws_cloudwatch_log_group.research.arn}:log-stream:${local.deletion_rehearsal_prefix}/${local.deletion_rehearsal_container}/*"]
  }

  statement {
    sid       = "LauncherNeverOverwritesAParameter"
    effect    = "Deny"
    actions   = ["ssm:PutParameter"]
    resources = ["*"]

    condition {
      test     = "Bool"
      variable = "ssm:Overwrite"
      values   = ["true"]
    }
  }

  statement {
    sid           = "LauncherWritesNoOtherParameter"
    effect        = "Deny"
    actions       = ["ssm:PutParameter", "ssm:DeleteParameter", "ssm:DeleteParameters", "ssm:LabelParameterVersion"]
    not_resources = local.deletion_rehearsal_launcher_parameter_arns
  }

  statement {
    sid    = "LauncherReadsNoParameterAndDecryptsNothing"
    effect = "Deny"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:GetParametersByPath",
      "ssm:GetParameterHistory",
      "kms:Decrypt",
      "kms:Encrypt",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "LauncherDefinesNothingOpensNoSessionAndTouchesNoObject"
    effect = "Deny"
    actions = [
      "ecs:RegisterTaskDefinition",
      "ecs:DeregisterTaskDefinition",
      "ecs:CreateService",
      "ecs:UpdateService",
      "ecs:CreateCluster",
      "ecs:PutClusterCapacityProviders",
      "ecs:ExecuteCommand",
      "s3:*",
      "secretsmanager:*",
      "sts:AssumeRole",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "deletion_rehearsal_launcher" {
  count = local.deletion_rehearsal_count

  name        = "${var.name_prefix}-deletion-rehearsal-launcher"
  description = "Proposed ADR-0050 deletion rehearsal launcher: one revision, the deletion and execution roles passable, two create-only parameters, the rehearsal streams. Launcher set only."
  policy      = data.aws_iam_policy_document.deletion_rehearsal_launcher.json

  tags = {
    Purpose = "deletion-rehearsal"
  }
}

resource "aws_ssoadmin_permission_set" "deletion_rehearsal_launcher" {
  count = local.deletion_rehearsal_count

  name             = local.deletion_rehearsal_set
  description      = "Proposed ADR-0050 deletion rehearsal launcher: run the rehearsal revision as the deletion role, observe it, collect its receipt."
  instance_arn     = var.identity_center_instance_arn
  session_duration = local.production_session_duration

  tags = {
    Purpose = "deletion-rehearsal"
  }
}

resource "aws_ssoadmin_customer_managed_policy_attachment" "deletion_rehearsal_launcher" {
  count = local.deletion_rehearsal_count

  instance_arn       = var.identity_center_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.deletion_rehearsal_launcher[0].arn

  customer_managed_policy_reference {
    name = aws_iam_policy.deletion_rehearsal_launcher[0].name
    path = aws_iam_policy.deletion_rehearsal_launcher[0].path
  }
}

# ---------------------------------------------------------------------------
# The assignment -- STAGE B AND OPEN, never before
# ---------------------------------------------------------------------------

resource "aws_ssoadmin_account_assignment" "deletion_rehearsal_launcher" {
  count = local.deletion_rehearsal_assignment_count

  instance_arn       = var.identity_center_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.deletion_rehearsal_launcher[0].arn

  principal_id   = local.production_operator_group_id
  principal_type = "GROUP"

  target_id   = local.production_target_account_id
  target_type = "AWS_ACCOUNT"

  lifecycle {
    precondition {
      condition     = local.production_account_consistent
      error_message = "An assignment may target only the account the provider acts in and the qualification package is bound to."
    }
  }

  depends_on = [
    aws_ssoadmin_customer_managed_policy_attachment.deletion_rehearsal_launcher,
  ]
}
