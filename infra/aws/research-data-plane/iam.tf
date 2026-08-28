# IAM -- least privilege, two roles, no humans.
#
# Two roles, deliberately separate, because they are trusted at different moments
# and by different things:
#
#   EXECUTION role  used by the ECS agent BEFORE the container starts, to pull the
#                   image and create the log stream. It never sees research data.
#   TASK role       used by the code INSIDE the container. It reaches the buckets
#                   and, later, one secret. It cannot pull images.
#
# Collapsing them into one role is the common shortcut and it is wrong here: it
# would give application code the ability to read the registry, and would give the
# infrastructure agent the ability to read licensed data.
#
# NO IAM USER AND NO ACCESS KEY IS CREATED ANYWHERE IN THIS CONFIGURATION.
# A long-lived access key is a credential that must then be stored, rotated and
# eventually deleted. Roles issue short-lived credentials automatically and there
# is nothing to leak. Adding a user here would be a governed change.
#
# There is no `"*"` action and no `"*"` resource except where the AWS API itself
# admits no alternative -- see the note on ecr:GetAuthorizationToken below.

# ---------------------------------------------------------------------------
# Trust policy shared by both roles
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }

    # Confused-deputy protection: the ECS service may assume these roles only on
    # behalf of THIS account. Without it the service principal is trusted
    # globally. The account id is read from the caller at apply time and is never
    # written into a committed file.
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

# ---------------------------------------------------------------------------
# Execution role -- image pull and log stream creation, nothing else
# ---------------------------------------------------------------------------

resource "aws_iam_role" "task_execution" {
  name               = "${var.name_prefix}-task-execution"
  description        = "ECS agent role: pulls the research image and opens a log stream. No data access."
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

data "aws_iam_policy_document" "task_execution" {
  # Scoped to THIS repository, rather than the AWS-managed
  # AmazonECSTaskExecutionRolePolicy, which permits pulling from every repository
  # in the account.
  statement {
    sid    = "PullResearchImage"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
    ]
    resources = [aws_ecr_repository.research.arn]
  }

  # `ecr:GetAuthorizationToken` is an account-level operation that does not
  # support resource-level permissions; AWS requires "*" for it. That is one named
  # action on "*", not a wildcard action, and it grants only the ability to obtain
  # a registry login token -- which is useless without the scoped pull permissions
  # above.
  statement {
    sid       = "GetRegistryAuthToken"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "WriteTaskLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.research.arn}:*"]
  }
}

resource "aws_iam_role_policy" "task_execution" {
  name   = "${var.name_prefix}-task-execution"
  role   = aws_iam_role.task_execution.id
  policy = data.aws_iam_policy_document.task_execution.json
}

# ---------------------------------------------------------------------------
# Task role -- what the research code itself may touch
# ---------------------------------------------------------------------------

resource "aws_iam_role" "task" {
  name               = "${var.name_prefix}-task"
  description        = "Research container role: the two research buckets, and later one provider secret."
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

data "aws_iam_policy_document" "task" {
  statement {
    sid    = "ListResearchBuckets"
    effect = "Allow"
    actions = [
      "s3:ListBucket",
      "s3:ListBucketMultipartUploads",
      "s3:GetBucketLocation",
    ]
    resources = [aws_s3_bucket.licensed.arn, aws_s3_bucket.control.arn]
  }

  statement {
    sid    = "ReadWriteLicensedObjects"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
    ]
    resources = ["${aws_s3_bucket.licensed.arn}/*"]
  }

  # `s3:DeleteObject` and `s3:AbortMultipartUpload` are present because DELETION
  # IS A LICENSING REQUIREMENT, not a convenience. A role that can ingest data it
  # is contractually obliged to be able to destroy, but cannot destroy it, is the
  # wrong role. Immutability is enforced in software by content addressing and
  # append-only publication, not by withholding the delete permission.

  statement {
    sid    = "ReadWriteControlObjects"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
    ]
    resources = ["${aws_s3_bucket.control.arn}/*"]
  }

  # No `s3:DeleteObject` on the control bucket. Manifests, lineage and deletion
  # receipts are governance evidence; a research task has no reason to remove
  # them, and the absence of the permission is what makes that structural rather
  # than aspirational.

  statement {
    sid    = "WriteTaskLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.research.arn}:*"]
  }

  # Provider secret read access, created ONLY if secret ARNs are supplied at apply
  # time. `provider_secret_arns` is empty by default and empty is the correct
  # current value: no provider is selected (G1 OPEN), no licence is resolved
  # (G3 OPEN), and no credential exists. This configuration creates no secret and
  # stores no secret value -- it records the interface, and nothing else.
  dynamic "statement" {
    for_each = length(var.provider_secret_arns) > 0 ? [1] : []

    content {
      sid    = "ReadProviderCredential"
      effect = "Allow"
      actions = [
        "secretsmanager:GetSecretValue",
        "ssm:GetParameter",
        "ssm:GetParameters",
      ]
      resources = var.provider_secret_arns
    }
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "${var.name_prefix}-task"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}
