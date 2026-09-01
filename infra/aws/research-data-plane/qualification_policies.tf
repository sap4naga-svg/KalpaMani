# The two ADR-0018 qualification permission sets -- POLICIES ONLY, ATTACHED TO NOTHING.
#
# ADR-0018 s.10 designs two least-privilege actors for the bounded private empirical
# qualification: an ACQUISITION actor that writes evidence and an ASSESSMENT actor
# that reads it. ADR-0019 then amended s.10.1 after a feasibility review established
# that AWS maps HeadObject to `s3:GetObject` and publishes no independent metadata
# action -- so the acquisition actor is now WRITE-ONLY at the IAM layer, not merely
# in the shape of its code. ADR-0020 moved one key class, the qualification payload,
# from a content address to a request-scoped one; the prefixes below are that layout.
#
# WHAT THIS FILE IS
#
#   Two customer-managed IAM policies, and nothing else. They express exactly the
#   permission sets ADR-0018 s.10.1 (as amended by ADR-0019 s.4.1) and s.10.2
#   describe, scoped to the object prefixes the merged key builders actually
#   produce.
#
# WHAT THIS FILE DELIBERATELY IS NOT
#
#   NO `aws_iam_role`. NO `assume_role_policy`. NO attachment of any kind.
#
#   That is not caution for its own sake -- the trust principal is genuinely not
#   determined by accepted repository authority, and guessing one would be a design
#   decision taken in a Terraform file. ADR-0018 s.6.1 and s.6.2 describe both
#   processes as operator entry points that PIN THE GOVERNED AWS PROFILE and pass
#   the governed identity gate; the merged entry points construct their clients
#   directly and call no `sts:AssumeRole`. So the ECS service principal that the
#   research task, execution and deletion roles use in iam.tf would contradict the
#   execution model the ADR describes, and no other principal is named anywhere in
#   accepted authority.
#
#   A managed policy attached to no principal GRANTS NOTHING. It is a reviewable,
#   deployable statement of an accepted permission set, in the same posture as the
#   deletion role in iam.tf, which is committed and unusable because nothing can
#   assume it. Naming the holder of these two policies is a separate architecture
#   decision and a separate authorization.
#
# WHAT IT DOES NOT TOUCH
#
#   No bucket is created, and no bucket property is changed. Every qualification
#   object lives in the EXISTING licensed bucket in storage.tf, under prefixes the
#   deletion runbook already covers. Public-access blocks, bucket-owner ownership,
#   SSE-S3 encryption, the TLS-only bucket policy, disabled versioning, the
#   multipart-abort lifecycle rule and the separated deletion role are all
#   unchanged. SSE-KMS is not introduced: ADR-0019 s.3 records why converting the
#   licensed bucket to KMS would not rescue the boundary and would break the
#   operation it was meant to permit.
#
#   NO CONTROL-bucket authority appears here, in either policy. CONTROL publication
#   is DEFERRED.
#
# APPLYING THIS IS A SEPARATE, UNGRANTED AUTHORIZATION. Writing infrastructure code
# is not mutating infrastructure; ADR-0018 s.10.4 says it in one sentence --
# designing a role is not creating one.

locals {
  # The three Stage-3A datasets, in the plan model's canonical order. They are the
  # same three as `EMPIRICAL_DATASETS` in
  # `src/kalpamani/data/qualify/sharadar/plan.py`; a test compares this list against
  # that constant, so the two cannot drift into a policy that scopes a prefix no key
  # builder produces -- or misses one it does.
  qualification_datasets = ["tickers", "stocks", "actions"]

  # Object prefixes, written out rather than generated. Each one is a physical key
  # prefix inside the licensed bucket -- physical, because `physical_key()` drops the
  # logical `licensed/` component that selects the store.
  #
  #   claims    bronze/_acquisition_claims/<payload-digest>/<run-id>.json
  #   payloads  bronze/sharadar/<dataset>/qualification/<execution>/requests/<NN>/sha256/<digest>
  #   records   bronze/sharadar/<dataset>/acquisitions/<payload-digest>/<run-id>.json
  #   locator   qualification/sharadar/locators/<execution-id>.json
  #   report    qualification/sharadar/reports/<run-a>/<run-b>/<assessment>.json
  #
  # The bucket ARN is a reference, never a literal: a bucket name in a public
  # repository is an identifier, and variables.tf keeps it out of every committed
  # file.
  qualification_claim_objects = "${aws_s3_bucket.licensed.arn}/bronze/_acquisition_claims/*"

  qualification_payload_objects = [
    "${aws_s3_bucket.licensed.arn}/bronze/sharadar/tickers/qualification/*",
    "${aws_s3_bucket.licensed.arn}/bronze/sharadar/stocks/qualification/*",
    "${aws_s3_bucket.licensed.arn}/bronze/sharadar/actions/qualification/*",
  ]

  qualification_record_objects = [
    "${aws_s3_bucket.licensed.arn}/bronze/sharadar/tickers/acquisitions/*",
    "${aws_s3_bucket.licensed.arn}/bronze/sharadar/stocks/acquisitions/*",
    "${aws_s3_bucket.licensed.arn}/bronze/sharadar/actions/acquisitions/*",
  ]

  qualification_locator_objects = "${aws_s3_bucket.licensed.arn}/qualification/sharadar/locators/*"
  qualification_report_objects  = "${aws_s3_bucket.licensed.arn}/qualification/sharadar/reports/*"

  # Everything the acquisition actor writes: three Bronze objects per completed
  # request, and one locator published last.
  qualification_acquisition_writes = concat(
    [local.qualification_claim_objects],
    local.qualification_payload_objects,
    local.qualification_record_objects,
    [local.qualification_locator_objects],
  )

  # Everything the assessment actor reads as evidence: both locators, 96 acquisition
  # records and 96 payloads. ZERO claims -- ADR-0018 s.9.4 records
  # `acquisition-claim GetObject: ZERO`, because a claim is validated from the
  # locator rather than retrieved -- so the claim prefix is absent here, and the deny
  # statement below keeps it absent if this list is ever widened carelessly.
  qualification_assessment_reads = concat(
    [local.qualification_locator_objects],
    local.qualification_record_objects,
    local.qualification_payload_objects,
  )
}

# ---------------------------------------------------------------------------
# Acquisition -- write-only, and write-only at the IAM layer
# ---------------------------------------------------------------------------
#
# ADR-0019 s.4.1: the acquisition actor receives `s3:PutObject` only, on its
# authorized prefixes; no `s3:GetObject`, no `s3:GetObjectVersion`, no
# `s3:GetObjectAttributes`, no listing, copy or deletion authority, and no CONTROL
# authority. It keeps its one governed secret retrieval and nothing else.
#
# `s3:AbortMultipartUpload` is absent, unlike the routine research role in iam.tf.
# The write-only publisher issues one `put_object` per object and has no multipart
# path, so the permission would be authority nothing uses.
#
# The 412 fail-closed rule is an application property and is NOT claimed here. IAM
# cannot see that `IfNoneMatch: *` was sent; it authorizes the action, not the
# request shape. What IAM does carry is the half the application cannot: a
# compromised process holding these credentials still cannot read a licensed object,
# because the permission is not there.

data "aws_iam_policy_document" "qualification_acquisition" {
  statement {
    sid       = "PublishQualificationEvidence"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = local.qualification_acquisition_writes
  }

  # Belt and braces, on purpose. Omitting a permission is the least-privilege style
  # used throughout iam.tf and it is enough on its own -- but ADR-0019 s.8 rests the
  # two-actor split on a compromise argument that has to hold at the identity layer,
  # and an explicit deny survives a second policy being attached to the same
  # principal later.
  statement {
    sid    = "AcquisitionNeverReadsOrDeletes"
    effect = "Deny"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
      "s3:GetObjectAttributes",
      "s3:GetObjectVersionAttributes",
      "s3:DeleteObject",
      "s3:DeleteObjectVersion",
    ]
    resources = ["${aws_s3_bucket.licensed.arn}/*"]
  }

  # `s3:ListBucket` is denied at the bucket ARN, because that is the resource a
  # listing names.
  statement {
    sid    = "AcquisitionNeverEnumeratesTheLicensedStore"
    effect = "Deny"
    actions = [
      "s3:ListBucket",
      "s3:ListBucketVersions",
      "s3:ListBucketMultipartUploads",
    ]
    resources = [aws_s3_bucket.licensed.arn]
  }

  # One governed secret retrieval, and only if a secret ARN is supplied at apply
  # time. `provider_secret_arns` is empty by default and empty is the correct current
  # value, so by default this policy grants no Secrets Manager access at all.
  # Narrower than the routine research role in iam.tf, which also grants the SSM
  # parameter reads: the acquisition entry point calls `get_secret_value` and nothing
  # else, so nothing else is granted.
  dynamic "statement" {
    for_each = length(var.provider_secret_arns) > 0 ? [1] : []

    content {
      sid       = "RetrieveTheGovernedProviderCredential"
      effect    = "Allow"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = var.provider_secret_arns
    }
  }
}

resource "aws_iam_policy" "qualification_acquisition" {
  name        = "${var.name_prefix}-qualification-acquisition"
  description = "ADR-0018/0019 qualification acquisition: write-only licensed evidence publication. Attached to nothing."
  policy      = data.aws_iam_policy_document.qualification_acquisition.json

  tags = {
    Purpose = "qualification-acquisition"
  }
}

# ---------------------------------------------------------------------------
# Assessment -- reads evidence, reaches no provider and no credential
# ---------------------------------------------------------------------------
#
# ADR-0018 s.10.2: exact `GetObject` on the locator prefix and on the referenced
# licensed Bronze objects, and conditional publication under the report prefix. Not
# provider-credential or secret access, not provider network access, not listing,
# delete, copy, Bronze publication, CONTROL access or bucket administration.
#
# THE REPORT PREFIX IS READABLE, AND THAT IS DELIBERATE RATHER THAN OVERLOOKED. The
# accepted conditional report publication resolves an occupied name from metadata
# after a 412 -- one `HeadObject`, at most once -- and AWS authorizes HeadObject
# through `s3:GetObject`. There is no independent `s3:HeadObject` action to grant
# instead; that is the finding ADR-0019 s.3 records. So the read grant on the report
# prefix is what makes the accepted 195-to-196 assessment envelope deployable, and it
# is scoped to the reports this actor writes.
#
# The claim prefix is absent from the read grant and explicitly denied: ADR-0018
# s.9.4 fixes acquisition-claim GetObject at ZERO.

data "aws_iam_policy_document" "qualification_assessment" {
  statement {
    sid       = "ReadQualificationEvidenceByExactName"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = local.qualification_assessment_reads
  }

  statement {
    sid       = "PublishOneCombinedPrivateReport"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = [local.qualification_report_objects]
  }

  # HeadObject uses the object-read permission. Scoped to the report prefix alone, so
  # the confirmation this actor needs for its own write does not become a read grant
  # anywhere else.
  statement {
    sid       = "ConfirmAnOccupiedReportNameFromMetadata"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = [local.qualification_report_objects]
  }

  # The assessment actor must never be able to write acquisition evidence, read a
  # claim, or destroy anything. Denied explicitly for the same reason as the
  # acquisition denies: the separation is meant to hold at the identity layer.
  statement {
    sid    = "AssessmentNeverWritesOrDeletesAcquisitionEvidence"
    effect = "Deny"
    actions = [
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:DeleteObjectVersion",
    ]
    resources = concat(
      [local.qualification_claim_objects, local.qualification_locator_objects],
      local.qualification_payload_objects,
      local.qualification_record_objects,
    )
  }

  statement {
    sid       = "AssessmentNeverReadsAnAcquisitionClaim"
    effect    = "Deny"
    actions   = ["s3:GetObject"]
    resources = [local.qualification_claim_objects]
  }

  statement {
    sid    = "AssessmentNeverEnumeratesTheLicensedStore"
    effect = "Deny"
    actions = [
      "s3:ListBucket",
      "s3:ListBucketVersions",
      "s3:ListBucketMultipartUploads",
    ]
    resources = [aws_s3_bucket.licensed.arn]
  }

  # No credential, and no way to acquire one. A provider request needs the API key,
  # and this actor cannot retrieve it from any of the stores a credential could live
  # in -- so "a provider failure cannot become an assessment result" holds at the
  # identity layer and not only in the code. The wildcard resource is on a DENY and
  # grants nothing; a secret ARN is an identifier and cannot be committed here to
  # narrow it, and narrowing a prohibition to one ARN would leave every other secret
  # reachable.
  statement {
    sid    = "AssessmentNeverRetrievesACredential"
    effect = "Deny"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:BatchGetSecretValue",
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:GetParametersByPath",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "qualification_assessment" {
  name        = "${var.name_prefix}-qualification-assessment"
  description = "ADR-0018 qualification assessment: exact evidence reads and one private report. Attached to nothing."
  policy      = data.aws_iam_policy_document.qualification_assessment.json

  tags = {
    Purpose = "qualification-assessment"
  }
}
