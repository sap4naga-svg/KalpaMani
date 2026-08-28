# Toolchain and provider constraints.
#
# Pinned by minor version rather than exactly, so a security fix is available
# without a code change while a major-version bump stays a deliberate decision.

terraform {
  # >= 1.10 is required by the backend below, not a preference: `use_lockfile`
  # is the S3 native locking mechanism and does not exist before 1.10. Leaving
  # this at 1.6 would let an older Terraform init a backend whose locking it
  # silently ignores, which is worse than refusing to run.
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # The exact provider build is pinned by `.terraform.lock.hcl`, which IS
  # committed. The constraint above says which versions are acceptable; the lock
  # file records which one was actually selected and the checksums of its
  # packages, so a later `init` on another machine resolves to the same provider
  # rather than to whatever is newest that day.

  # Remote state in S3, with S3 native locking.
  #
  # DELIBERATELY EMPTY. Every value that would go here -- bucket name, key,
  # region -- is an identifier, and a state bucket name in a public repository
  # tells an attacker exactly which object to try to read. The real values live
  # in an uncommitted backend file and are supplied at init:
  #
  #     terraform init -backend-config=<local backend file>
  #
  # `use_lockfile = true` (Terraform >= 1.10) holds the lock as an object beside
  # the state rather than in DynamoDB. One fewer always-on billable resource, and
  # one fewer thing to forget to delete.
  #
  # The state bucket is INFRASTRUCTURE-CONTROL data, not licensed vendor data, so
  # it takes the opposite durability posture to the licensed bucket in storage.tf:
  # versioning is ENABLED there, because a corrupted state file is unrecoverable
  # and no vendor deletion obligation reaches it. It is bootstrapped separately --
  # a backend cannot create the bucket it stores its own state in.
  #
  # State must NEVER be committed. It records bucket names, ARNs, account
  # identifiers and -- for some resource types -- secret values in plaintext.
  # `.gitignore` excludes it; that exclusion is a safety control, not tidiness.
  backend "s3" {}
}
