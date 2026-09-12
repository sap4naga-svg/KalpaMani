# ADR-0036 production data-plane principals -- THE HOLDERS.
#
# Two actors, four Identity Center permission sets, two ECS task roles, and two
# launcher permission sets (ADR-0036 s.2.1, s.2.9). Every human principal is an
# Identity Center permission set assigned to the governed operator group, exactly
# as ADR-0021 chose for qualification; every compute principal is an IAM role that
# ONLY an ECS task in this account can assume. No IAM user, no access key, no
# cross-account principal, no `sts:AssumeRole` from application code.
#
# THE STAGE GATE IS THE STRUCTURE OF THIS FILE
#
#   stage a   permission sets, their customer-managed-policy references, the task
#             roles and their policy attachments. A permission set with no
#             assignment and a task role no launcher may pass grant nothing.
#   stage b   the four `aws_ssoadmin_account_assignment` resources -- the ONLY
#             resources in this configuration gated on stage b, because an
#             assignment is what turns a declared permission set into an authority
#             a person can hold, and ADR-0036 s.2.7 makes R-3 verification the
#             prerequisite of exactly that.
#
# THE FOUNDATION'S OWN TASK ROLE IS NOT HERE. `aws_iam_role.task` in iam.tf can
# list, read and write both buckets and read a provider secret -- the one-actor
# combination ADR-0036 refuses. Neither production actor uses it, no launcher may
# pass it (production_policies.tf closes PassRole with NotResource), and its
# narrowing or retirement is a separate decision under ADR-0007.
#
# NO LIVE DISCOVERY beyond what main.tf already resolves at plan time. The account
# id in the trust conditions is the caller's, which the provider binding already
# constrains to `allowed_account_ids`.

locals {
  # Permission-set names exactly as ADR-0036 accepts them, measured by the
  # repository's guard against the pinned provider's 1-32 bound (ADR-0022).
  production_acquisition_permission_set = "KalpaManiProductionAcquire" # 26
  production_build_permission_set       = "KalpaManiResearchBuild"     # 22
  production_acquire_launcher_set       = "KalpaManiAcquireLauncher"   # 24
  production_build_launcher_set         = "KalpaManiBuildLauncher"     # 22

  # One hour, as for qualification (ADR-0036 s.2.1).
  production_session_duration = "PT1H"

  # The task-role names the identity gate compiles per image (ADR-0036 s.2.5).
  production_acquire_task_role_name = "kalpamani-production-acquire-task"
  production_build_task_role_name   = "kalpamani-research-build-task"
}

# ---------------------------------------------------------------------------
# Task roles -- assumable by ECS tasks in this account, and by nothing else
# ---------------------------------------------------------------------------
#
# ADR-0036 s.2.7 (trust): `ecs-tasks.amazonaws.com` only, with `aws:SourceAccount`
# pinned to this account and `aws:SourceArn` scoped to this account's ECS. No `AWS`
# principal, so no human and no other service can assume either role.

data "aws_iam_policy_document" "production_task_trust" {
  statement {
    sid     = "OnlyEcsTasksInThisAccount"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"]
    }
  }
}

resource "aws_iam_role" "production_acquire_task" {
  count = local.production_count_a

  name               = local.production_acquire_task_role_name
  description        = "ADR-0036 production acquisition task role: write-only Bronze, one secret, task bootstrap reads. Stage a."
  assume_role_policy = data.aws_iam_policy_document.production_task_trust.json

  tags = {
    Purpose = "production-acquisition"
  }
}

resource "aws_iam_role_policy_attachment" "production_acquire_task_data_plane" {
  count = local.production_count_a

  role       = aws_iam_role.production_acquire_task[0].name
  policy_arn = aws_iam_policy.production_acquisition[0].arn
}

resource "aws_iam_role_policy_attachment" "production_acquire_task_bootstrap" {
  count = local.production_count_a

  role       = aws_iam_role.production_acquire_task[0].name
  policy_arn = aws_iam_policy.production_acquire_task_bootstrap[0].arn
}

resource "aws_iam_role" "production_build_task" {
  count = local.production_count_a

  name               = local.production_build_task_role_name
  description        = "ADR-0036 research build task role: exact Bronze reads, Silver/Gold/manifest writes, no secret, task bootstrap reads. Stage a."
  assume_role_policy = data.aws_iam_policy_document.production_task_trust.json

  tags = {
    Purpose = "production-build"
  }
}

resource "aws_iam_role_policy_attachment" "production_build_task_data_plane" {
  count = local.production_count_a

  role       = aws_iam_role.production_build_task[0].name
  policy_arn = aws_iam_policy.production_build[0].arn
}

resource "aws_iam_role_policy_attachment" "production_build_task_bootstrap" {
  count = local.production_count_a

  role       = aws_iam_role.production_build_task[0].name
  policy_arn = aws_iam_policy.production_build_task_bootstrap[0].arn
}

# ---------------------------------------------------------------------------
# Human permission sets -- data plane plus human bootstrap (stage a)
# ---------------------------------------------------------------------------

resource "aws_ssoadmin_permission_set" "production_acquisition" {
  count = local.production_count_a

  name             = local.production_acquisition_permission_set
  description      = "ADR-0036 production acquisition actor (human): data plane plus input materialization. Stage a."
  instance_arn     = var.identity_center_instance_arn
  session_duration = local.production_session_duration

  tags = {
    Purpose = "production-acquisition"
  }
}

resource "aws_ssoadmin_customer_managed_policy_attachment" "production_acquisition_data_plane" {
  count = local.production_count_a

  instance_arn       = var.identity_center_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.production_acquisition[0].arn

  customer_managed_policy_reference {
    name = aws_iam_policy.production_acquisition[0].name
    path = aws_iam_policy.production_acquisition[0].path
  }
}

resource "aws_ssoadmin_customer_managed_policy_attachment" "production_acquisition_human_bootstrap" {
  count = local.production_count_a

  instance_arn       = var.identity_center_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.production_acquisition[0].arn

  customer_managed_policy_reference {
    name = aws_iam_policy.production_acquisition_human_bootstrap[0].name
    path = aws_iam_policy.production_acquisition_human_bootstrap[0].path
  }
}

resource "aws_ssoadmin_permission_set" "production_build" {
  count = local.production_count_a

  name             = local.production_build_permission_set
  description      = "ADR-0036 research build actor (human): data plane plus input materialization. Stage a."
  instance_arn     = var.identity_center_instance_arn
  session_duration = local.production_session_duration

  tags = {
    Purpose = "production-build"
  }
}

resource "aws_ssoadmin_customer_managed_policy_attachment" "production_build_data_plane" {
  count = local.production_count_a

  instance_arn       = var.identity_center_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.production_build[0].arn

  customer_managed_policy_reference {
    name = aws_iam_policy.production_build[0].name
    path = aws_iam_policy.production_build[0].path
  }
}

resource "aws_ssoadmin_customer_managed_policy_attachment" "production_build_human_bootstrap" {
  count = local.production_count_a

  instance_arn       = var.identity_center_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.production_build[0].arn

  customer_managed_policy_reference {
    name = aws_iam_policy.production_build_human_bootstrap[0].name
    path = aws_iam_policy.production_build_human_bootstrap[0].path
  }
}

# ---------------------------------------------------------------------------
# Launcher permission sets -- one per actor (stage a)
# ---------------------------------------------------------------------------

resource "aws_ssoadmin_permission_set" "production_acquire_launcher" {
  count = local.production_count_a

  name             = local.production_acquire_launcher_set
  description      = "ADR-0036 acquisition launcher: run one revision, pass two roles, write the placement release. Stage a."
  instance_arn     = var.identity_center_instance_arn
  session_duration = local.production_session_duration

  tags = {
    Purpose = "production-acquisition"
  }
}

resource "aws_ssoadmin_customer_managed_policy_attachment" "production_acquire_launcher" {
  count = local.production_count_a

  instance_arn       = var.identity_center_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.production_acquire_launcher[0].arn

  customer_managed_policy_reference {
    name = aws_iam_policy.production_acquire_launcher[0].name
    path = aws_iam_policy.production_acquire_launcher[0].path
  }
}

resource "aws_ssoadmin_permission_set" "production_build_launcher" {
  count = local.production_count_a

  name             = local.production_build_launcher_set
  description      = "ADR-0036 build launcher: run one revision, pass two roles, write the placement release. Stage a."
  instance_arn     = var.identity_center_instance_arn
  session_duration = local.production_session_duration

  tags = {
    Purpose = "production-build"
  }
}

resource "aws_ssoadmin_customer_managed_policy_attachment" "production_build_launcher" {
  count = local.production_count_a

  instance_arn       = var.identity_center_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.production_build_launcher[0].arn

  customer_managed_policy_reference {
    name = aws_iam_policy.production_build_launcher[0].name
    path = aws_iam_policy.production_build_launcher[0].path
  }
}

# ---------------------------------------------------------------------------
# Assignments -- STAGE B ONLY: after R-3 is verified, and never before
# ---------------------------------------------------------------------------
#
# Four assignments, one group, one account. These are the only resources gated on
# `production_count_b`, which `production_variables.tf` refuses without the R-3
# verification digest. Until they exist, every permission set above is a
# declaration nobody can hold.

resource "aws_ssoadmin_account_assignment" "production_acquisition" {
  count = local.production_count_b

  instance_arn       = var.identity_center_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.production_acquisition[0].arn

  principal_id   = local.production_operator_group_id
  principal_type = "GROUP"

  target_id   = local.production_target_account_id
  target_type = "AWS_ACCOUNT"

  depends_on = [
    aws_ssoadmin_customer_managed_policy_attachment.production_acquisition_data_plane,
    aws_ssoadmin_customer_managed_policy_attachment.production_acquisition_human_bootstrap,
  ]
}

resource "aws_ssoadmin_account_assignment" "production_build" {
  count = local.production_count_b

  instance_arn       = var.identity_center_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.production_build[0].arn

  principal_id   = local.production_operator_group_id
  principal_type = "GROUP"

  target_id   = local.production_target_account_id
  target_type = "AWS_ACCOUNT"

  depends_on = [
    aws_ssoadmin_customer_managed_policy_attachment.production_build_data_plane,
    aws_ssoadmin_customer_managed_policy_attachment.production_build_human_bootstrap,
  ]
}

resource "aws_ssoadmin_account_assignment" "production_acquire_launcher" {
  count = local.production_count_b

  instance_arn       = var.identity_center_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.production_acquire_launcher[0].arn

  principal_id   = local.production_operator_group_id
  principal_type = "GROUP"

  target_id   = local.production_target_account_id
  target_type = "AWS_ACCOUNT"

  depends_on = [
    aws_ssoadmin_customer_managed_policy_attachment.production_acquire_launcher,
  ]
}

resource "aws_ssoadmin_account_assignment" "production_build_launcher" {
  count = local.production_count_b

  instance_arn       = var.identity_center_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.production_build_launcher[0].arn

  principal_id   = local.production_operator_group_id
  principal_type = "GROUP"

  target_id   = local.production_target_account_id
  target_type = "AWS_ACCOUNT"

  depends_on = [
    aws_ssoadmin_customer_managed_policy_attachment.production_build_launcher,
  ]
}
