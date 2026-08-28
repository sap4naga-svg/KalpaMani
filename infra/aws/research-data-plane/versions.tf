# Toolchain and provider constraints.
#
# Pinned by minor version rather than exactly, so a security fix is available
# without a code change while a major-version bump stays a deliberate decision.

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # NOTE: no backend block.
  #
  # State is local-only and, in practice, non-existent: this configuration has
  # never been applied. A remote backend needs an encrypted, versioned state
  # bucket with locking, and choosing one is part of the separate authorization
  # that permits `terraform apply` at all (ADR-0007 Follow-ups).
  #
  # State must NEVER be committed. It records bucket names, ARNs, account
  # identifiers and — for some resource types — secret values in plaintext.
  # `.gitignore` excludes it; that exclusion is a safety control, not tidiness.
}
