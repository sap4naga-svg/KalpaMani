# S3 -- the two-bucket research store.
#
# The licensed bucket holds anything from which vendor rows could be recovered.
# The control bucket holds manifests, lineage, receipts and approved
# non-reconstructable outputs, and nothing else. See ADR-0007 §3.
#
# READ THIS BEFORE "IMPROVING" THE LICENSED BUCKET.
#
# The licensed bucket deliberately has NO versioning, NO Object Lock, NO
# replication and NO archival lifecycle. Those are not oversights and they are not
# a security weakness; every one of them creates a copy that a vendor deletion
# obligation would have to reach, and the obligation can start without notice
# (ADR-0007 Context; docs/runbooks/vendor-data-cloud-deletion.md).
#
# Bronze immutability does not depend on any of them. It comes from
# content-addressed object names plus append-only software rules, which the A1
# kernel already implements: an artifact is named by the SHA-256 of its contents,
# and a version is never rewritten. Turning versioning on would add a second,
# weaker mechanism for a property already guaranteed, at the price of making
# deletion unprovable.

# ---------------------------------------------------------------------------
# Licensed-data bucket
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "licensed" {
  bucket = local.licensed_bucket_name

  # No `object_lock_enabled`. Object Lock can only be enabled at creation, and it
  # makes deletion impossible until expiry BY DESIGN -- including for the account
  # root. That is directly incompatible with a 30-day deletion obligation.

  tags = {
    Name      = local.licensed_bucket_name
    DataClass = "licensed"
    Deletion  = "vendor-terminable"
  }
}

resource "aws_s3_bucket_public_access_block" "licensed" {
  bucket = aws_s3_bucket.licensed.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "licensed" {
  bucket = aws_s3_bucket.licensed.id

  # Disables ACLs entirely. Access is governed by policy alone, which removes an
  # entire class of accidental exposure rather than configuring it correctly.
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "licensed" {
  bucket = aws_s3_bucket.licensed.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_versioning" "licensed" {
  bucket = aws_s3_bucket.licensed.id

  # DISABLED, deliberately and permanently. See the header of this file.
  #
  # If this is ever changed, the deletion runbook stops being correct: it would
  # have to enumerate object VERSIONS and DELETE MARKERS rather than objects,
  # because a bucket holding only delete markers lists as empty and still holds
  # the data. Changing this is an ADR, not an edit.
  versioning_configuration {
    status = "Disabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "licensed" {
  bucket = aws_s3_bucket.licensed.id

  # The ONLY lifecycle rule on this bucket, and it is a deletion aid rather than
  # an archival policy. Incomplete multipart upload parts are stored and billed
  # but do not appear in an object listing, so a delete-everything-you-can-list
  # procedure reports success and leaves vendor bytes behind.
  #
  # There is deliberately NO transition to Glacier or any archival class: it would
  # make provable deletion slower and more expensive for data whose lifetime is
  # the subscription's anyway.
  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = var.multipart_abort_days
    }
  }
}

resource "aws_s3_bucket_policy" "licensed" {
  bucket = aws_s3_bucket.licensed.id
  policy = data.aws_iam_policy_document.licensed_bucket.json

  # Block Public Access must exist before a policy is attached, so a
  # misconfiguration can never be public even momentarily.
  depends_on = [aws_s3_bucket_public_access_block.licensed]
}

data "aws_iam_policy_document" "licensed_bucket" {
  # TLS-only. Without this, a plaintext request is served normally; the bucket
  # default encryption protects data at rest and says nothing about the wire.
  statement {
    sid    = "DenyNonTLSRequests"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions   = ["s3:*"]
    resources = [aws_s3_bucket.licensed.arn, "${aws_s3_bucket.licensed.arn}/*"]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  # No Allow statement. Nothing grants access to this bucket except the task role
  # in iam.tf, and there is no cross-account principal, no anonymous principal and
  # no public grant anywhere in this configuration.
}

# ---------------------------------------------------------------------------
# Control / permitted-output bucket
# ---------------------------------------------------------------------------
#
# Same access posture, opposite durability posture. Nothing here is subject to a
# vendor deletion obligation -- which is exactly what promoting an artifact into
# this bucket asserts -- so versioning is safe and useful here.

resource "aws_s3_bucket" "control" {
  bucket = local.control_bucket_name

  tags = {
    Name      = local.control_bucket_name
    DataClass = "control"
    Deletion  = "retained"
  }
}

resource "aws_s3_bucket_public_access_block" "control" {
  bucket = aws_s3_bucket.control.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "control" {
  bucket = aws_s3_bucket.control.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "control" {
  bucket = aws_s3_bucket.control.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_versioning" "control" {
  bucket = aws_s3_bucket.control.id

  # Enabled here, and only here. A manifest or a deletion receipt overwritten by
  # mistake is a governance-evidence loss with no compensating vendor obligation.
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "control" {
  bucket = aws_s3_bucket.control.id

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = var.multipart_abort_days
    }
  }

  # Bounds how many superseded manifest versions accumulate. Generous, because
  # provenance evidence is small and losing it has no upside.
  rule {
    id     = "expire-old-noncurrent-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days           = 365
      newer_noncurrent_versions = 10
    }
  }
}

resource "aws_s3_bucket_policy" "control" {
  bucket = aws_s3_bucket.control.id
  policy = data.aws_iam_policy_document.control_bucket.json

  depends_on = [aws_s3_bucket_public_access_block.control]
}

data "aws_iam_policy_document" "control_bucket" {
  statement {
    sid    = "DenyNonTLSRequests"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions   = ["s3:*"]
    resources = [aws_s3_bucket.control.arn, "${aws_s3_bucket.control.arn}/*"]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}
