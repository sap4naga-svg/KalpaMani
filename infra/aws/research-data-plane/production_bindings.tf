# ADR-0036 production data-plane principals -- THE KEY AND THE TASK BINDINGS.
#
# A container has no private root and no owner-only ACL, so a task receives its
# runtime binding from a per-actor SSM SecureString parameter encrypted under a
# customer-managed KMS key (ADR-0036 s.2.5). The foundation has no KMS key today,
# and the AWS-managed `aws/ssm` key cannot carry a key policy -- so one is declared
# here, with a policy of exactly four kinds of statement:
#
#   administration + binding materialization   the Terraform-apply principal
#   task decryption                             the two task roles, by exact ARN
#   human input materialization                 the two actor permission sets, by
#                                               generated-role prefix
#   launcher release materialization            the two launcher sets, by prefix
#
# Every usage statement carries `kms:ViaService = ssm.<region>.amazonaws.com` and
# an exact `kms:EncryptionContext:PARAMETER_ARN`, so the key is usable only through
# Parameter Store and only for the parameter a statement names. Identity Center
# generated roles rotate their suffix, so the human and launcher statements match
# the account principal under an `aws:PrincipalArn` prefix pattern rather than a
# pinned ARN -- ADR-0021's stance, unchanged.
#
# THE TWO BINDING PARAMETERS ARE MATERIALIZED BY THIS CONFIGURATION, under the
# application authorization (ADR-0036 s.2.5 "Parameter ownership"). Their content
# is the account, region, bucket and profile this configuration already holds as
# inputs, plus the provenance block supplied at apply time. The values land in
# Terraform state -- which already records the bucket name and the account id, is
# git-ignored and lives in the versioned state bucket. No input or release
# parameter is declared here: those are created per run by the human principal
# and the launcher respectively, and Terraform owns neither.
#
# Standard tier, on purpose: a binding is a few hundred bytes, standard-tier
# values are encrypted directly under the key with `kms:Encrypt`, and no
# lifecycle policy applies -- a binding does not expire; it is replaced by a later
# apply.

data "aws_iam_policy_document" "production_task_bindings_key" {
  statement {
    sid     = "AdministerTheKeyAndMaterializeBindings"
    effect  = "Allow"
    actions = ["kms:*"]

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }

    resources = ["*"]

    condition {
      test     = "StringLike"
      variable = "aws:PrincipalArn"
      values   = [var.production_apply_principal_arn_pattern]
    }
  }

  dynamic "statement" {
    for_each = local.production_stage_a ? [1] : []

    content {
      sid     = "AcquisitionTaskDecryptsItsParameters"
      effect  = "Allow"
      actions = ["kms:Decrypt"]

      principals {
        type        = "AWS"
        identifiers = [aws_iam_role.production_acquire_task[0].arn]
      }

      resources = ["*"]

      condition {
        test     = "StringEquals"
        variable = "kms:EncryptionContext:PARAMETER_ARN"
        values   = local.production_acquisition_task_parameter_arns
      }

      condition {
        test     = "StringEquals"
        variable = "kms:ViaService"
        values   = [local.production_ssm_via_service]
      }
    }
  }

  dynamic "statement" {
    for_each = local.production_stage_a ? [1] : []

    content {
      sid     = "BuildTaskDecryptsItsParameters"
      effect  = "Allow"
      actions = ["kms:Decrypt"]

      principals {
        type        = "AWS"
        identifiers = [aws_iam_role.production_build_task[0].arn]
      }

      resources = ["*"]

      condition {
        test     = "StringEquals"
        variable = "kms:EncryptionContext:PARAMETER_ARN"
        values   = local.production_build_task_parameter_arns
      }

      condition {
        test     = "StringEquals"
        variable = "kms:ViaService"
        values   = [local.production_ssm_via_service]
      }
    }
  }

  statement {
    sid     = "AcquisitionHumanGeneratesTheInputDataKey"
    effect  = "Allow"
    actions = ["kms:GenerateDataKey"]

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }

    resources = ["*"]

    condition {
      test     = "StringLike"
      variable = "aws:PrincipalArn"
      values   = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/aws-reserved/sso.amazonaws.com/*/AWSReservedSSO_${local.production_acquisition_permission_set}_*"]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:PARAMETER_ARN"
      values   = [local.production_acquisition_input_parameter_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = [local.production_ssm_via_service]
    }
  }

  statement {
    sid     = "BuildHumanGeneratesTheInputDataKey"
    effect  = "Allow"
    actions = ["kms:GenerateDataKey"]

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }

    resources = ["*"]

    condition {
      test     = "StringLike"
      variable = "aws:PrincipalArn"
      values   = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/aws-reserved/sso.amazonaws.com/*/AWSReservedSSO_${local.production_build_permission_set}_*"]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:PARAMETER_ARN"
      values   = [local.production_build_input_parameter_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = [local.production_ssm_via_service]
    }
  }

  statement {
    sid     = "AcquireLauncherGeneratesTheReleaseDataKey"
    effect  = "Allow"
    actions = ["kms:GenerateDataKey"]

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }

    resources = ["*"]

    condition {
      test     = "StringLike"
      variable = "aws:PrincipalArn"
      values   = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/aws-reserved/sso.amazonaws.com/*/AWSReservedSSO_${local.production_acquire_launcher_set}_*"]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:PARAMETER_ARN"
      values   = [local.production_acquisition_release_parameter_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = [local.production_ssm_via_service]
    }
  }

  statement {
    sid     = "BuildLauncherGeneratesTheReleaseDataKey"
    effect  = "Allow"
    actions = ["kms:GenerateDataKey"]

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }

    resources = ["*"]

    condition {
      test     = "StringLike"
      variable = "aws:PrincipalArn"
      values   = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/aws-reserved/sso.amazonaws.com/*/AWSReservedSSO_${local.production_build_launcher_set}_*"]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:PARAMETER_ARN"
      values   = [local.production_build_release_parameter_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = [local.production_ssm_via_service]
    }
  }
}

resource "aws_kms_key" "production_task_bindings" {
  count = local.production_count_a

  description         = "ADR-0036 task bindings, inputs and placement releases. Usable only through Parameter Store. Stage a."
  enable_key_rotation = true
  policy              = data.aws_iam_policy_document.production_task_bindings_key.json

  # Thirty days is the maximum deletion window; a key that protects nothing
  # licensed can afford the longest recovery window AWS offers.
  deletion_window_in_days = 30

  tags = {
    Purpose = "production-task-bindings"
  }
}

resource "aws_kms_alias" "production_task_bindings" {
  count = local.production_count_a

  name          = "alias/kalpamani-task-bindings"
  target_key_id = aws_kms_key.production_task_bindings[0].key_id
}

# ---------------------------------------------------------------------------
# The two task runtime bindings (ADR-0036 s.2.5; shape per ADR-0023)
# ---------------------------------------------------------------------------

locals {
  production_acquisition_binding = {
    schema_version       = 1
    binding_kind         = "kalpamani-production-acquisition-runtime"
    contract_id          = "kalpamani-production-acquisition-runtime-binding/v1"
    aws_partition        = "aws"
    aws_region           = var.aws_region
    target_account_id    = local.production_target_account_id
    acquisition_profile  = "kalpamani-production-acquisition"
    licensed_bucket_name = aws_s3_bucket.licensed.id
    provenance           = var.production_binding_provenance
  }

  production_build_binding = {
    schema_version       = 1
    binding_kind         = "kalpamani-research-build-runtime"
    contract_id          = "kalpamani-research-build-runtime-binding/v1"
    aws_partition        = "aws"
    aws_region           = var.aws_region
    target_account_id    = local.production_target_account_id
    build_profile        = "kalpamani-research-build"
    licensed_bucket_name = aws_s3_bucket.licensed.id
    provenance           = var.production_binding_provenance
  }
}

resource "aws_ssm_parameter" "production_acquisition_binding" {
  count = local.production_count_a

  name        = "/kalpamani/production/acquisition/runtime-binding"
  description = "ADR-0036 acquisition task runtime binding. Read by the acquisition task role only."
  type        = "SecureString"
  tier        = "Standard"
  key_id      = aws_kms_key.production_task_bindings[0].arn
  value       = jsonencode(local.production_acquisition_binding)

  tags = {
    Purpose = "production-acquisition"
  }
}

resource "aws_ssm_parameter" "production_build_binding" {
  count = local.production_count_a

  name        = "/kalpamani/production/research-build/runtime-binding"
  description = "ADR-0036 research build task runtime binding. Read by the build task role only."
  type        = "SecureString"
  tier        = "Standard"
  key_id      = aws_kms_key.production_task_bindings[0].arn
  value       = jsonencode(local.production_build_binding)

  tags = {
    Purpose = "production-build"
  }
}
