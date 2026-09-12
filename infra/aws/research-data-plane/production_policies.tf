# ADR-0036 production data-plane principals -- THE POLICY DOCUMENTS.
#
# Eight customer-managed policies, in three layers that ADR-0036 s.2.1 keeps apart
# on purpose and that this file keeps apart by construction:
#
#   data-plane      production_acquisition, production_build
#                   S3 and the one secret, and NOTHING ELSE: no ssm:* and no kms:*
#                   statement of either effect, so a deny shared by a permission set
#                   and a task role can never block the one principal kind that is
#                   permitted to write a parameter.
#   task bootstrap  production_acquire_task_bootstrap, production_build_task_bootstrap
#                   attached to the task role only: exact parameter reads, scoped
#                   decryption, and explicit denies on every parameter write.
#   human bootstrap production_acquisition_human_bootstrap, production_build_human_bootstrap
#                   attached to the actor's permission set only: create-only input
#                   materialization, one delete, scoped data-key generation, and an
#                   explicit deny on every binding-parameter read.
#   launcher        production_acquire_launcher, production_build_launcher
#                   one RunTask resource, a two-role PassRole allowlist closed by
#                   NotResource, and the placement-release write -- no data-plane
#                   statement at all (ADR-0036 s.2.9).
#
# Every prefix is written out as a literal under the licensed bucket's ARN
# reference, as qualification_policies.tf does, so the repository's HCL parser can
# resolve it and assert on it. Every parameter and key ARN is a reference or an
# interpolation over inputs; no identifier is committed here.
#
# WHAT THIS FILE DELIBERATELY IS NOT
#
#   NOT a change to any qualification policy. The two ADR-0018 documents are
#   untouched, and every production document DENIES the qualification prefixes.
#   NOT a change to the routine research role in iam.tf.
#   NOT attached to anything here: attachments are production_principals.tf, and
#   every resource in both files carries the stage gate of production_variables.tf.
#
# APPLYING THIS IS A SEPARATE, UNGRANTED AUTHORIZATION. ADR-0036 s.2.7: stage a is
# not complete until R-3 is verified, and no assignment exists until it is.

locals {
  # The three datasets ADR-0034 selected, in canonical order -- the same list the
  # qualification policies scope, compared against the plan constant by a test.
  production_datasets = ["tickers", "stocks", "actions"]

  # Physical prefixes inside the licensed bucket -- ADR-0036 s.2.2 -- s.2.4 as
  # amended by ADR-0037 (disjoint production namespaces, effective on merge).
  #
  #   payloads   bronze/sharadar/<dataset>/production/objects/sha256/<digest>
  #   records    bronze/sharadar/<dataset>/production/acquisitions/<...>
  #   locator    bronze/sharadar/_indexes/<run-id>.json
  #   claims     bronze/_production_claims/<...>
  #   outputs    silver/*, gold/*, manifests/*
  #
  # NONE of these is a prefix any earlier package writes. The traced layouts of
  # the objects already in the bucket, and the code that names them, are:
  #
  #   ADR-0009/0011 general Bronze bridge (publication.py; used by ADR-0017 attempt two)
  #     bronze/sharadar/<dataset>/objects/sha256/<digest>
  #     bronze/sharadar/<dataset>/acquisitions/<digest>/<run-id>.json
  #     bronze/_acquisition_claims/<digest>/<run-id>.json
  #   ADR-0018/0020 qualification (qualify/sharadar/publication.py, locator.py, report.py)
  #     bronze/sharadar/<dataset>/qualification/<execution>/requests/<NN>/sha256/<digest>
  #     bronze/sharadar/<dataset>/acquisitions/<digest>/<run-id>.json   (records, shared bridge)
  #     bronze/_acquisition_claims/<digest>/<run-id>.json               (claims, shared bridge)
  #     qualification/sharadar/locators/<execution-id>.json
  #     qualification/sharadar/reports/<run-a>/<run-b>/<assessment>.json
  #
  # The `production/` path segment and the `_production_claims` namespace are what
  # keep the two apart: a production grant reaches no qualification or ADR-0017
  # object, and the bucket-policy statements of storage.tf govern no prefix any
  # earlier package writes. Every earlier namespace appears below ONLY in the
  # `production_foreign_bronze_objects` deny list; a test builds real
  # qualification keys with the merged key builders and proves none of them
  # matches a production grant or the bucket-policy scope.
  production_payload_objects = [
    "${aws_s3_bucket.licensed.arn}/bronze/sharadar/tickers/production/objects/sha256/*",
    "${aws_s3_bucket.licensed.arn}/bronze/sharadar/stocks/production/objects/sha256/*",
    "${aws_s3_bucket.licensed.arn}/bronze/sharadar/actions/production/objects/sha256/*",
  ]

  production_record_objects = [
    "${aws_s3_bucket.licensed.arn}/bronze/sharadar/tickers/production/acquisitions/*",
    "${aws_s3_bucket.licensed.arn}/bronze/sharadar/stocks/production/acquisitions/*",
    "${aws_s3_bucket.licensed.arn}/bronze/sharadar/actions/production/acquisitions/*",
  ]

  production_index_objects = "${aws_s3_bucket.licensed.arn}/bronze/sharadar/_indexes/*"
  production_claim_objects = "${aws_s3_bucket.licensed.arn}/bronze/_production_claims/*"

  # Every Bronze namespace an EARLIER package writes, denied to both production
  # actors for every action. Listed by the layouts traced above, not by guess.
  production_foreign_bronze_objects = [
    "${aws_s3_bucket.licensed.arn}/bronze/_acquisition_claims/*",
    "${aws_s3_bucket.licensed.arn}/bronze/sharadar/tickers/objects/sha256/*",
    "${aws_s3_bucket.licensed.arn}/bronze/sharadar/stocks/objects/sha256/*",
    "${aws_s3_bucket.licensed.arn}/bronze/sharadar/actions/objects/sha256/*",
    "${aws_s3_bucket.licensed.arn}/bronze/sharadar/tickers/acquisitions/*",
    "${aws_s3_bucket.licensed.arn}/bronze/sharadar/stocks/acquisitions/*",
    "${aws_s3_bucket.licensed.arn}/bronze/sharadar/actions/acquisitions/*",
  ]

  production_output_objects = [
    "${aws_s3_bucket.licensed.arn}/silver/*",
    "${aws_s3_bucket.licensed.arn}/gold/*",
    "${aws_s3_bucket.licensed.arn}/manifests/*",
  ]

  production_qualification_objects = [
    "${aws_s3_bucket.licensed.arn}/qualification/*",
    "${aws_s3_bucket.licensed.arn}/bronze/sharadar/tickers/qualification/*",
    "${aws_s3_bucket.licensed.arn}/bronze/sharadar/stocks/qualification/*",
    "${aws_s3_bucket.licensed.arn}/bronze/sharadar/actions/qualification/*",
  ]

  # Everything the acquisition actor writes; everything the build actor reads.
  production_acquisition_writes = concat(
    local.production_payload_objects,
    local.production_record_objects,
    [local.production_index_objects, local.production_claim_objects],
  )

  production_build_reads = concat(
    local.production_payload_objects,
    local.production_record_objects,
    [local.production_index_objects],
    local.production_output_objects,
  )

  # The licensed bucket and everything in it -- the ONLY S3 resources either
  # data-plane actor may touch. Every other bucket (CONTROL, state, ECR layers,
  # anything) is denied by a NotResource statement, so no ARN needs naming.
  production_licensed_resources = [
    aws_s3_bucket.licensed.arn,
    "${aws_s3_bucket.licensed.arn}/*",
  ]

  # The fixed parameter names ADR-0036 compiles (s.2.5, s.2.6, s.2.9). Built as
  # ARNs over inputs; the binding parameters are also resources in
  # production_bindings.tf, and the input and release parameters are created per
  # run by the human principal and the launcher respectively -- Terraform owns
  # neither, and names them here only to scope permissions.
  production_parameter_arn_prefix = "arn:aws:ssm:${var.aws_region}:${local.production_target_account_id}:parameter"

  production_acquisition_binding_parameter_arn = "${local.production_parameter_arn_prefix}/kalpamani/production/acquisition/runtime-binding"
  production_acquisition_input_parameter_arn   = "${local.production_parameter_arn_prefix}/kalpamani/production/acquisition/input"
  production_acquisition_release_parameter_arn = "${local.production_parameter_arn_prefix}/kalpamani/production/acquisition/release"
  production_build_binding_parameter_arn       = "${local.production_parameter_arn_prefix}/kalpamani/production/research-build/runtime-binding"
  production_build_input_parameter_arn         = "${local.production_parameter_arn_prefix}/kalpamani/production/research-build/input"
  production_build_release_parameter_arn       = "${local.production_parameter_arn_prefix}/kalpamani/production/research-build/release"

  production_acquisition_task_parameter_arns = [
    local.production_acquisition_binding_parameter_arn,
    local.production_acquisition_input_parameter_arn,
    local.production_acquisition_release_parameter_arn,
  ]

  production_build_task_parameter_arns = [
    local.production_build_binding_parameter_arn,
    local.production_build_input_parameter_arn,
    local.production_build_release_parameter_arn,
  ]

  production_ssm_via_service = "ssm.${var.aws_region}.amazonaws.com"

  # Object-level actions no production actor may ever hold on the licensed bucket.
  # Delete stays with the deletion role; ACL, retention and legal hold have no
  # place on a deletion-first bucket; multipart has no place under prefixes whose
  # objects are single conditional puts.
  production_forbidden_object_actions = [
    "s3:DeleteObject",
    "s3:DeleteObjectVersion",
    "s3:PutObjectAcl",
    "s3:PutObjectVersionAcl",
    "s3:RestoreObject",
    "s3:PutObjectRetention",
    "s3:PutObjectLegalHold",
    "s3:AbortMultipartUpload",
    "s3:ListMultipartUploadParts",
  ]

  production_listing_actions = [
    "s3:ListBucket",
    "s3:ListBucketVersions",
    "s3:ListBucketMultipartUploads",
  ]

  production_read_actions = [
    "s3:GetObject",
    "s3:GetObjectVersion",
    "s3:GetObjectAttributes",
    "s3:GetObjectVersionAttributes",
  ]

  # Service families neither data-plane actor may touch (ADR-0036 s.2.2, s.2.3).
  # `ecs:*` is here because the launcher, not the actor, launches.
  production_forbidden_service_actions = [
    "iam:*",
    "sts:AssumeRole",
    "ec2:*",
    "ecs:*",
  ]
}

# ---------------------------------------------------------------------------
# Data plane -- acquisition: bounded secret access, write-only Bronze
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "production_acquisition" {
  # ADR-0036 s.2.2: conditional PutObject only. The four conditions are the
  # identity-policy half of s.2.7; the bucket-policy half is in storage.tf. SSE-S3
  # explicit, If-None-Match required, object-creating requests only (no multipart
  # part), no copy source.
  statement {
    sid       = "PublishProductionBronzeConditionally"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = local.production_acquisition_writes

    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-server-side-encryption"
      values   = ["AES256"]
    }

    condition {
      test     = "Null"
      variable = "s3:if-none-match"
      values   = ["false"]
    }

    condition {
      test     = "Bool"
      variable = "s3:ObjectCreationOperation"
      values   = ["true"]
    }

    condition {
      test     = "Null"
      variable = "s3:x-amz-copy-source"
      values   = ["true"]
    }
  }

  # Write-only at the IAM layer, exactly as ADR-0019 requires and ADR-0036 s.2.2
  # restates: it cannot read what it wrote, cannot list, cannot delete, cannot copy.
  statement {
    sid       = "AcquisitionNeverReadsDeletesOrAlters"
    effect    = "Deny"
    actions   = concat(local.production_read_actions, local.production_forbidden_object_actions)
    resources = ["${aws_s3_bucket.licensed.arn}/*"]
  }

  statement {
    sid       = "AcquisitionNeverEnumeratesTheLicensedStore"
    effect    = "Deny"
    actions   = local.production_listing_actions
    resources = [aws_s3_bucket.licensed.arn]
  }

  statement {
    sid       = "AcquisitionNeverCopies"
    effect    = "Deny"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.licensed.arn}/*"]

    condition {
      test     = "Null"
      variable = "s3:x-amz-copy-source"
      values   = ["false"]
    }
  }

  # Nothing outside the licensed bucket: CONTROL, the state bucket, the ECR layer
  # bucket and every bucket not named here, without naming any of them.
  statement {
    sid           = "AcquisitionTouchesNoOtherBucket"
    effect        = "Deny"
    actions       = ["s3:*"]
    not_resources = local.production_licensed_resources
  }

  statement {
    sid       = "AcquisitionNeverTouchesQualification"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = local.production_qualification_objects
  }

  # The general Bronze bridge's namespaces -- qualification records and claims,
  # and ADR-0017's three objects -- are not production's either (ADR-0037).
  statement {
    sid       = "AcquisitionNeverTouchesEarlierBronzeNamespaces"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = local.production_foreign_bronze_objects
  }

  # One secret, by exact ARN, and every other Secrets Manager capability denied --
  # including GetSecretValue on any other secret, which is what keeps the
  # qualification credential a different resource in more than name.
  dynamic "statement" {
    for_each = var.production_acquisition_secret_arn != "" ? [1] : []

    content {
      sid       = "RetrieveTheOneProductionCredential"
      effect    = "Allow"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = [var.production_acquisition_secret_arn]
    }
  }

  dynamic "statement" {
    for_each = var.production_acquisition_secret_arn != "" ? [1] : []

    content {
      sid           = "AcquisitionRetrievesNoOtherSecret"
      effect        = "Deny"
      actions       = ["secretsmanager:GetSecretValue", "secretsmanager:BatchGetSecretValue"]
      not_resources = [var.production_acquisition_secret_arn]
    }
  }

  statement {
    sid    = "AcquisitionNeverAdministersSecrets"
    effect = "Deny"
    actions = [
      "secretsmanager:DescribeSecret",
      "secretsmanager:ListSecrets",
      "secretsmanager:ListSecretVersionIds",
      "secretsmanager:GetResourcePolicy",
      "secretsmanager:PutSecretValue",
      "secretsmanager:UpdateSecret",
      "secretsmanager:DeleteSecret",
      "secretsmanager:RestoreSecret",
      "secretsmanager:RotateSecret",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "AcquisitionHoldsNoServiceAuthority"
    effect    = "Deny"
    actions   = local.production_forbidden_service_actions
    resources = ["*"]
  }
}

resource "aws_iam_policy" "production_acquisition" {
  count = local.production_count_a

  name        = "${var.name_prefix}-production-acquisition"
  description = "ADR-0036 production acquisition data plane: one secret, conditional write-only Bronze. Stage a."
  policy      = data.aws_iam_policy_document.production_acquisition.json

  tags = {
    Purpose = "production-acquisition"
  }
}

# ---------------------------------------------------------------------------
# Data plane -- research build: exact reads, licensed Silver/Gold writes, no secret
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "production_build" {
  # ADR-0036 s.2.3 and s.2.4: the IAM half of the exact-read boundary is PREFIX
  # confinement -- these wildcard grants. Locator-only reads within them are the
  # application's invariant and are not claimed here.
  statement {
    sid       = "ReadProductionBronzeAndOwnOutputs"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = local.production_build_reads
  }

  statement {
    sid       = "PublishSilverGoldAndManifestsConditionally"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = local.production_output_objects

    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-server-side-encryption"
      values   = ["AES256"]
    }

    condition {
      test     = "Null"
      variable = "s3:if-none-match"
      values   = ["false"]
    }

    condition {
      test     = "Bool"
      variable = "s3:ObjectCreationOperation"
      values   = ["true"]
    }

    condition {
      test     = "Null"
      variable = "s3:x-amz-copy-source"
      values   = ["true"]
    }
  }

  statement {
    sid       = "BuildNeverDeletesOrAlters"
    effect    = "Deny"
    actions   = local.production_forbidden_object_actions
    resources = ["${aws_s3_bucket.licensed.arn}/*"]
  }

  statement {
    sid       = "BuildNeverEnumeratesTheLicensedStore"
    effect    = "Deny"
    actions   = local.production_listing_actions
    resources = [aws_s3_bucket.licensed.arn]
  }

  statement {
    sid       = "BuildNeverCopies"
    effect    = "Deny"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.licensed.arn}/*"]

    condition {
      test     = "Null"
      variable = "s3:x-amz-copy-source"
      values   = ["false"]
    }
  }

  # Claims are validated from the locator, never read (ADR-0018 s.9.4, ADR-0036
  # s.2.3); Bronze is never written by the build actor.
  statement {
    sid       = "BuildNeverReadsAClaim"
    effect    = "Deny"
    actions   = local.production_read_actions
    resources = [local.production_claim_objects]
  }

  statement {
    sid       = "BuildNeverWritesBronze"
    effect    = "Deny"
    actions   = ["s3:PutObject"]
    resources = concat(local.production_acquisition_writes, ["${aws_s3_bucket.licensed.arn}/bronze/*"])
  }

  statement {
    sid           = "BuildTouchesNoOtherBucket"
    effect        = "Deny"
    actions       = ["s3:*"]
    not_resources = local.production_licensed_resources
  }

  statement {
    sid       = "BuildNeverTouchesQualification"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = local.production_qualification_objects
  }

  statement {
    sid       = "BuildNeverTouchesEarlierBronzeNamespaces"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = local.production_foreign_bronze_objects
  }

  # No secret of any kind. The wildcard is on a DENY and grants nothing.
  statement {
    sid       = "BuildHoldsNoSecret"
    effect    = "Deny"
    actions   = ["secretsmanager:*"]
    resources = ["*"]
  }

  statement {
    sid       = "BuildHoldsNoServiceAuthority"
    effect    = "Deny"
    actions   = local.production_forbidden_service_actions
    resources = ["*"]
  }
}

resource "aws_iam_policy" "production_build" {
  count = local.production_count_a

  name        = "${var.name_prefix}-production-build"
  description = "ADR-0036 research build data plane: exact Bronze reads, conditional Silver/Gold/manifest writes, no secret. Stage a."
  policy      = data.aws_iam_policy_document.production_build.json

  tags = {
    Purpose = "production-build"
  }
}

# ---------------------------------------------------------------------------
# Task bootstrap -- attached to the task role only (ADR-0036 s.2.5)
# ---------------------------------------------------------------------------
#
# Three exact parameter reads (binding, input, release) and the scoped decryption
# Parameter Store performs on the task's behalf: `kms:Decrypt` is a PERMISSION the
# task needs and a network path it does not -- Parameter Store calls KMS, with the
# parameter ARN as encryption context, and `kms:ViaService` makes the grant usable
# through Parameter Store alone. A task never writes, never enumerates.

data "aws_iam_policy_document" "production_acquire_task_bootstrap" {
  statement {
    sid       = "ReadThisActorsThreeParameters"
    effect    = "Allow"
    actions   = ["ssm:GetParameter"]
    resources = local.production_acquisition_task_parameter_arns
  }

  dynamic "statement" {
    for_each = local.production_stage_a ? [1] : []

    content {
      sid       = "DecryptThoseParametersThroughParameterStoreOnly"
      effect    = "Allow"
      actions   = ["kms:Decrypt"]
      resources = [aws_kms_key.production_task_bindings[0].arn]

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

resource "aws_iam_policy" "production_acquire_task_bootstrap" {
  count = local.production_count_a

  name        = "${var.name_prefix}-production-acquire-task-bootstrap"
  description = "ADR-0036 acquisition task bootstrap: three exact parameter reads, scoped decrypt, no writes. Task role only. Stage a."
  policy      = data.aws_iam_policy_document.production_acquire_task_bootstrap.json

  tags = {
    Purpose = "production-acquisition"
  }
}

data "aws_iam_policy_document" "production_build_task_bootstrap" {
  statement {
    sid       = "ReadThisActorsThreeParameters"
    effect    = "Allow"
    actions   = ["ssm:GetParameter"]
    resources = local.production_build_task_parameter_arns
  }

  dynamic "statement" {
    for_each = local.production_stage_a ? [1] : []

    content {
      sid       = "DecryptThoseParametersThroughParameterStoreOnly"
      effect    = "Allow"
      actions   = ["kms:Decrypt"]
      resources = [aws_kms_key.production_task_bindings[0].arn]

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

resource "aws_iam_policy" "production_build_task_bootstrap" {
  count = local.production_count_a

  name        = "${var.name_prefix}-production-build-task-bootstrap"
  description = "ADR-0036 build task bootstrap: three exact parameter reads, scoped decrypt, no writes. Task role only. Stage a."
  policy      = data.aws_iam_policy_document.production_build_task_bootstrap.json

  tags = {
    Purpose = "production-build"
  }
}

# ---------------------------------------------------------------------------
# Human bootstrap -- attached to the actor's permission set only (ADR-0036 s.2.6)
# ---------------------------------------------------------------------------
#
# Create-only input materialization, one delete for cleanup, and the data-key
# generation an ADVANCED-tier SecureString needs (Parameter Store envelope-encrypts
# advanced values with a data key, so the writer needs GenerateDataKey, not
# Encrypt). Every binding-parameter read, every release read, every other
# parameter write and every decrypt is denied: a human writes an input, and does
# nothing else with Parameter Store.

data "aws_iam_policy_document" "production_acquisition_human_bootstrap" {
  statement {
    sid       = "CreateThisActorsInputOnce"
    effect    = "Allow"
    actions   = ["ssm:PutParameter"]
    resources = [local.production_acquisition_input_parameter_arn]

    condition {
      test     = "Bool"
      variable = "ssm:Overwrite"
      values   = ["false"]
    }
  }

  statement {
    sid       = "DeleteThisActorsInputAfterTheRun"
    effect    = "Allow"
    actions   = ["ssm:DeleteParameter"]
    resources = [local.production_acquisition_input_parameter_arn]
  }

  dynamic "statement" {
    for_each = local.production_stage_a ? [1] : []

    content {
      sid       = "GenerateTheInputsDataKeyThroughParameterStoreOnly"
      effect    = "Allow"
      actions   = ["kms:GenerateDataKey"]
      resources = [aws_kms_key.production_task_bindings[0].arn]

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
  }

  statement {
    sid       = "HumanNeverOverwritesAParameter"
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
    sid           = "HumanWritesNoOtherParameter"
    effect        = "Deny"
    actions       = ["ssm:PutParameter", "ssm:DeleteParameter", "ssm:DeleteParameters", "ssm:LabelParameterVersion"]
    not_resources = [local.production_acquisition_input_parameter_arn]
  }

  statement {
    sid    = "HumanReadsNoBindingInputOrRelease"
    effect = "Deny"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:GetParametersByPath",
      "ssm:GetParameterHistory",
    ]
    resources = concat(
      [local.production_acquisition_binding_parameter_arn, local.production_build_binding_parameter_arn],
      [local.production_build_input_parameter_arn],
      [local.production_acquisition_release_parameter_arn, local.production_build_release_parameter_arn],
    )
  }

  statement {
    sid       = "HumanNeverDecryptsOrEncryptsDirectly"
    effect    = "Deny"
    actions   = ["kms:Decrypt", "kms:Encrypt"]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "production_acquisition_human_bootstrap" {
  count = local.production_count_a

  name        = "${var.name_prefix}-production-acquisition-human-bootstrap"
  description = "ADR-0036 acquisition human bootstrap: create-only input, one delete, scoped data key. Permission set only. Stage a."
  policy      = data.aws_iam_policy_document.production_acquisition_human_bootstrap.json

  tags = {
    Purpose = "production-acquisition"
  }
}

data "aws_iam_policy_document" "production_build_human_bootstrap" {
  statement {
    sid       = "CreateThisActorsInputOnce"
    effect    = "Allow"
    actions   = ["ssm:PutParameter"]
    resources = [local.production_build_input_parameter_arn]

    condition {
      test     = "Bool"
      variable = "ssm:Overwrite"
      values   = ["false"]
    }
  }

  statement {
    sid       = "DeleteThisActorsInputAfterTheRun"
    effect    = "Allow"
    actions   = ["ssm:DeleteParameter"]
    resources = [local.production_build_input_parameter_arn]
  }

  dynamic "statement" {
    for_each = local.production_stage_a ? [1] : []

    content {
      sid       = "GenerateTheInputsDataKeyThroughParameterStoreOnly"
      effect    = "Allow"
      actions   = ["kms:GenerateDataKey"]
      resources = [aws_kms_key.production_task_bindings[0].arn]

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
  }

  statement {
    sid       = "HumanNeverOverwritesAParameter"
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
    sid           = "HumanWritesNoOtherParameter"
    effect        = "Deny"
    actions       = ["ssm:PutParameter", "ssm:DeleteParameter", "ssm:DeleteParameters", "ssm:LabelParameterVersion"]
    not_resources = [local.production_build_input_parameter_arn]
  }

  statement {
    sid    = "HumanReadsNoBindingInputOrRelease"
    effect = "Deny"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:GetParametersByPath",
      "ssm:GetParameterHistory",
    ]
    resources = concat(
      [local.production_acquisition_binding_parameter_arn, local.production_build_binding_parameter_arn],
      [local.production_acquisition_input_parameter_arn],
      [local.production_acquisition_release_parameter_arn, local.production_build_release_parameter_arn],
    )
  }

  statement {
    sid       = "HumanNeverDecryptsOrEncryptsDirectly"
    effect    = "Deny"
    actions   = ["kms:Decrypt", "kms:Encrypt"]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "production_build_human_bootstrap" {
  count = local.production_count_a

  name        = "${var.name_prefix}-production-build-human-bootstrap"
  description = "ADR-0036 build human bootstrap: create-only input, one delete, scoped data key. Permission set only. Stage a."
  policy      = data.aws_iam_policy_document.production_build_human_bootstrap.json

  tags = {
    Purpose = "production-build"
  }
}

# ---------------------------------------------------------------------------
# Launchers -- one per actor (ADR-0036 s.2.9)
# ---------------------------------------------------------------------------
#
# A single launcher holding PassRole on three roles would be an allowlist, not a
# binding: it could run the acquisition definition with the build role overridden
# in. Two launchers make the task-definition-to-role binding an IAM property: each
# may run exactly its actor's revision, pass exactly its actor's task role and the
# shared execution role, and the allowlist is closed by a NotResource deny that no
# later Allow can reopen. There is no other `iam:*` statement of either effect, so
# the PassRole grant is never overridden.
#
# The launcher also writes the placement release -- create-only, after the
# placement verification of s.2.9 -- and reads nothing: it can write a release it
# cannot read back.

data "aws_iam_policy_document" "production_acquire_launcher" {
  dynamic "statement" {
    for_each = local.production_stage_a ? [1] : []

    content {
      sid       = "RunExactlyThisActorsRevisionInTheOneCluster"
      effect    = "Allow"
      actions   = ["ecs:RunTask"]
      resources = [aws_ecs_task_definition.production_acquire[0].arn]

      condition {
        test     = "ArnEquals"
        variable = "ecs:cluster"
        values   = [aws_ecs_cluster.research.arn]
      }
    }
  }

  dynamic "statement" {
    for_each = local.production_stage_a ? [1] : []

    content {
      sid       = "PassExactlyTwoRolesToEcsTasks"
      effect    = "Allow"
      actions   = ["iam:PassRole"]
      resources = [aws_iam_role.production_acquire_task[0].arn, aws_iam_role.task_execution.arn]

      condition {
        test     = "StringEquals"
        variable = "iam:PassedToService"
        values   = ["ecs-tasks.amazonaws.com"]
      }
    }
  }

  dynamic "statement" {
    for_each = local.production_stage_a ? [1] : []

    content {
      sid           = "PassNoOtherRole"
      effect        = "Deny"
      actions       = ["iam:PassRole"]
      not_resources = [aws_iam_role.production_acquire_task[0].arn, aws_iam_role.task_execution.arn]
    }
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

  # Placement verification (s.2.9): the task's interface, subnet, security groups
  # and public-IP association. A describe-only action without resource-level
  # scoping.
  statement {
    sid       = "DescribeTheTasksNetworkInterface"
    effect    = "Allow"
    actions   = ["ec2:DescribeNetworkInterfaces"]
    resources = ["*"]
  }

  statement {
    sid       = "WriteThisActorsPlacementReleaseOnce"
    effect    = "Allow"
    actions   = ["ssm:PutParameter"]
    resources = [local.production_acquisition_release_parameter_arn]

    condition {
      test     = "Bool"
      variable = "ssm:Overwrite"
      values   = ["false"]
    }
  }

  statement {
    sid       = "DeleteThisActorsPlacementReleaseAfterTheRun"
    effect    = "Allow"
    actions   = ["ssm:DeleteParameter"]
    resources = [local.production_acquisition_release_parameter_arn]
  }

  dynamic "statement" {
    for_each = local.production_stage_a ? [1] : []

    content {
      sid       = "GenerateTheReleasesDataKeyThroughParameterStoreOnly"
      effect    = "Allow"
      actions   = ["kms:GenerateDataKey"]
      resources = [aws_kms_key.production_task_bindings[0].arn]

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
    not_resources = [local.production_acquisition_release_parameter_arn]
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
    sid    = "LauncherDefinesNothingAndOpensNoSession"
    effect = "Deny"
    actions = [
      "ecs:RegisterTaskDefinition",
      "ecs:DeregisterTaskDefinition",
      "ecs:CreateService",
      "ecs:UpdateService",
      "ecs:CreateCluster",
      "ecs:PutClusterCapacityProviders",
      "ecs:ExecuteCommand",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "production_acquire_launcher" {
  count = local.production_count_a

  name        = "${var.name_prefix}-production-acquire-launcher"
  description = "ADR-0036 acquisition launcher: one revision, two passable roles, placement release. Launcher set only. Stage a."
  policy      = data.aws_iam_policy_document.production_acquire_launcher.json

  tags = {
    Purpose = "production-acquisition"
  }
}

data "aws_iam_policy_document" "production_build_launcher" {
  dynamic "statement" {
    for_each = local.production_stage_a ? [1] : []

    content {
      sid       = "RunExactlyThisActorsRevisionInTheOneCluster"
      effect    = "Allow"
      actions   = ["ecs:RunTask"]
      resources = [aws_ecs_task_definition.production_build[0].arn]

      condition {
        test     = "ArnEquals"
        variable = "ecs:cluster"
        values   = [aws_ecs_cluster.research.arn]
      }
    }
  }

  dynamic "statement" {
    for_each = local.production_stage_a ? [1] : []

    content {
      sid       = "PassExactlyTwoRolesToEcsTasks"
      effect    = "Allow"
      actions   = ["iam:PassRole"]
      resources = [aws_iam_role.production_build_task[0].arn, aws_iam_role.task_execution.arn]

      condition {
        test     = "StringEquals"
        variable = "iam:PassedToService"
        values   = ["ecs-tasks.amazonaws.com"]
      }
    }
  }

  dynamic "statement" {
    for_each = local.production_stage_a ? [1] : []

    content {
      sid           = "PassNoOtherRole"
      effect        = "Deny"
      actions       = ["iam:PassRole"]
      not_resources = [aws_iam_role.production_build_task[0].arn, aws_iam_role.task_execution.arn]
    }
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
    sid       = "WriteThisActorsPlacementReleaseOnce"
    effect    = "Allow"
    actions   = ["ssm:PutParameter"]
    resources = [local.production_build_release_parameter_arn]

    condition {
      test     = "Bool"
      variable = "ssm:Overwrite"
      values   = ["false"]
    }
  }

  statement {
    sid       = "DeleteThisActorsPlacementReleaseAfterTheRun"
    effect    = "Allow"
    actions   = ["ssm:DeleteParameter"]
    resources = [local.production_build_release_parameter_arn]
  }

  dynamic "statement" {
    for_each = local.production_stage_a ? [1] : []

    content {
      sid       = "GenerateTheReleasesDataKeyThroughParameterStoreOnly"
      effect    = "Allow"
      actions   = ["kms:GenerateDataKey"]
      resources = [aws_kms_key.production_task_bindings[0].arn]

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
    not_resources = [local.production_build_release_parameter_arn]
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
    sid    = "LauncherDefinesNothingAndOpensNoSession"
    effect = "Deny"
    actions = [
      "ecs:RegisterTaskDefinition",
      "ecs:DeregisterTaskDefinition",
      "ecs:CreateService",
      "ecs:UpdateService",
      "ecs:CreateCluster",
      "ecs:PutClusterCapacityProviders",
      "ecs:ExecuteCommand",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "production_build_launcher" {
  count = local.production_count_a

  name        = "${var.name_prefix}-production-build-launcher"
  description = "ADR-0036 build launcher: one revision, two passable roles, placement release. Launcher set only. Stage a."
  policy      = data.aws_iam_policy_document.production_build_launcher.json

  tags = {
    Purpose = "production-build"
  }
}
