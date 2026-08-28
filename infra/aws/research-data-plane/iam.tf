# IAM -- least privilege, two roles, no humans.
#
# Three roles, deliberately separate, because they are trusted at different
# moments, by different things, and with different blast radii:
#
#   EXECUTION role  used by the ECS agent BEFORE the container starts, to pull the
#                   image and create the log stream. It never sees research data.
#   TASK role       used by the code INSIDE the container. It reads and writes the
#                   buckets and, later, reads one secret. It cannot pull images,
#                   it cannot write logs directly, and IT CANNOT DELETE.
#   DELETION role   used only by an authorized vendor-termination deletion or a
#                   rehearsal. It can destroy licensed objects and nothing else --
#                   it cannot read them, cannot write them, cannot touch the
#                   control bucket, and cannot read a secret.
#
# Collapsing execution and task into one role is the common shortcut and it is
# wrong here: it would give application code the ability to read the registry, and
# the infrastructure agent the ability to read licensed data.
#
# Separating DELETION from TASK matters more. The licensed bucket has no
# versioning, no replication and no backup by design, so every delete is
# irreversible. Standing delete authority on the role that runs routine ingestion
# would make an ordinary bug capable of destroying unrecoverable history.
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
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
    ]
    resources = ["${aws_s3_bucket.licensed.arn}/*"]
  }

  # NO `s3:DeleteObject`. An earlier revision granted it here and justified it as
  # "deletion is a licensing requirement, not a convenience". That reasoning was
  # wrong, and wrong in a way worth recording rather than quietly deleting.
  #
  # The deletion obligation binds KalpaMani AS A SYSTEM -- the owner must be able
  # to destroy the data within 30 days. It does not follow that the routine
  # ingestion role must carry the permission continuously. Those are different
  # claims, and conflating a system-level capability with a per-role grant is how
  # standing destructive authority gets justified.
  #
  # The consequence here is severe, because this bucket has no versioning, no
  # replication and no backup BY DESIGN (storage.tf). A stray delete is therefore
  # irreversible, and a re-fetch is not a restore -- it returns the vendor's data
  # as it stands today, which after a correction or backfill is a new artifact
  # with a new hash. The blast radius of a bug in routine research code was
  # "silently destroy unrecoverable history".
  #
  # Deletion authority now lives in `aws_iam_role.licensed_data_deletion` below,
  # which does nothing else and which nothing can currently assume.
  #
  # `s3:AbortMultipartUpload` stays: it cancels the task's OWN incomplete upload,
  # which is cleanup of work in progress, not destruction of published data.

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

  # NO CloudWatch Logs permissions on this role, and they are not missing.
  #
  # Under the ECS `awslogs` log driver the ECS agent collects the container's
  # stdout/stderr and delivers it, using the TASK EXECUTION role -- which holds
  # `logs:CreateLogStream` and `logs:PutLogEvents` and is the only role that needs
  # them. The application writes to stdout/stderr and never calls CloudWatch.
  #
  # Granting them here as well was redundant, and redundant log-write rights are
  # not harmless in this system: they would let application code call PutLogEvents
  # directly, which is exactly the path by which a provider payload or a
  # query-string API key reaches a durable, queryable store (ADR-0007 §8). Not
  # having the permission is a second, structural barrier behind the redaction
  # rules.
  #
  # If a future component genuinely needs to write to CloudWatch itself -- a
  # sidecar, or a metrics publisher -- that is a documented exception with its own
  # statement, not a quiet re-widening of this one.

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

# ---------------------------------------------------------------------------
# Deletion role -- vendor termination, and nothing else
# ---------------------------------------------------------------------------
#
# The ONLY identity in this configuration that may destroy licensed data.
#
# It exists because the licensed bucket has no versioning, no replication and no
# backup by design, which makes every delete irreversible. Standing destructive
# authority on the role that also runs routine ingestion turns an ordinary bug
# into unrecoverable data loss; separating them means a delete requires
# deliberately assuming a different identity.
#
# It is deliberately UNUSABLE AS COMMITTED. Nothing can assume it today:
#
#   - no ECS task definition exists anywhere in this configuration;
#   - no deletion task or workflow exists;
#   - no identity is granted `iam:PassRole` for it, so nothing can launch a task
#     that runs as this role;
#   - nothing runs, because no image has been built.
#
# Creating that task or workflow, and granting an operator identity the
# `iam:PassRole` needed to invoke it, is a SEPARATE authorization that has not
# been given. The role is committed now so the deletion procedure has a defined,
# reviewable identity before it is ever needed -- the same reason the deletion
# runbook is written before the data exists.
#
# Its use is limited to: an authorized vendor-termination deletion, or an
# authorized rehearsal against SYNTHETIC objects.

resource "aws_iam_role" "licensed_data_deletion" {
  name               = "${var.name_prefix}-licensed-data-deletion"
  description        = "Vendor-termination deletion of licensed data. Not the research role. Nothing can assume it yet."
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json

  tags = {
    Purpose = "vendor-termination-deletion"
  }
}

data "aws_iam_policy_document" "licensed_data_deletion" {
  # Bucket-level: enumerate the surface, and CONFIRM the properties the deletion
  # runbook asserts. Reading versioning, replication and lifecycle configuration
  # is what turns runbook steps 8 and 9 from "believed" into "evidenced" -- if
  # versioning was ever enabled the procedure must enumerate versions and delete
  # markers rather than objects, and it has to be able to find that out.
  statement {
    sid    = "InspectLicensedBucket"
    effect = "Allow"
    actions = [
      "s3:ListBucket",
      "s3:ListBucketMultipartUploads",
      "s3:ListBucketVersions",
      "s3:GetBucketLocation",
      "s3:GetBucketVersioning",
      "s3:GetReplicationConfiguration",
      "s3:GetLifecycleConfiguration",
    ]
    resources = [aws_s3_bucket.licensed.arn]
  }

  # Object-level: destroy, including versions and delete markers if versioning was
  # ever enabled, and the multipart parts that no object listing reveals.
  #
  # `s3:GetObject` is deliberately ABSENT. Deletion does not require reading the
  # data, and a role that can read every licensed object is a broader standing
  # capability than the job needs. Object counts and sizes for the deletion
  # receipt come from ListBucket, not from reading contents.
  #
  # `s3:PutObject` is deliberately ABSENT. This role destroys; it never writes.
  # The deletion receipt is written to the CONTROL bucket by the operator path,
  # not by this role -- which is also why this role has no access to the control
  # bucket at all. Nothing here can touch manifests, lineage or receipts.
  statement {
    sid    = "DeleteLicensedObjects"
    effect = "Allow"
    actions = [
      "s3:DeleteObject",
      "s3:DeleteObjectVersion",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
    ]
    resources = ["${aws_s3_bucket.licensed.arn}/*"]
  }

  # No secret access: deleting data needs no provider credential, and revoking
  # that credential is a separate step performed before deletion begins
  # (runbook step 2).
}

resource "aws_iam_role_policy" "licensed_data_deletion" {
  name   = "${var.name_prefix}-licensed-data-deletion"
  role   = aws_iam_role.licensed_data_deletion.id
  policy = data.aws_iam_policy_document.licensed_data_deletion.json
}
