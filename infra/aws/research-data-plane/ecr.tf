# ECR -- a private registry for future research images.
#
# NO IMAGE IS BUILT AND NO IMAGE IS PUSHED BY THIS CONFIGURATION. The repository
# is created empty, and stays empty until a separately authorized slice builds
# something to put in it.
#
# NOTHING SENSITIVE IS EVER BAKED INTO AN IMAGE: no credential, no provider API
# key, no licensed data, no `.env`. An image layer is a durable, distributable,
# content-addressed copy -- a key in a layer survives every rotation, and vendor
# rows in a layer are a copy the deletion runbook must find and destroy. Both are
# avoided by never putting them there, and the deletion runbook verifies the rule
# held rather than assuming it (step 11).

resource "aws_ecr_repository" "research" {
  name = "${var.name_prefix}-research"

  # Immutable tags: a tag, once pushed, cannot be re-pointed at different content.
  # Without this, `:latest` is a moving target and "which image produced this
  # research artifact" has no answer -- which would quietly undermine the
  # reproducibility model the whole point-in-time contract rests on.
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name = "${var.name_prefix}-research"
  }
}

resource "aws_ecr_lifecycle_policy" "research" {
  repository = aws_ecr_repository.research.name

  # Untagged images accumulate on every rebuild and bill per GB-month forever.
  # Tagged images are never expired here: a tagged image may be the one that
  # produced a manifest, and expiring it would break the ability to reproduce a
  # result. Retiring a tagged image is a deliberate act, not a lifecycle rule.
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images; they are rebuild residue, not provenance."
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = var.untagged_image_expiry_days
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}
