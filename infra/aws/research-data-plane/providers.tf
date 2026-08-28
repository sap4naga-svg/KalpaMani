# AWS provider configuration.
#
# `allowed_account_ids` is the guard that matters here. KalpaMani has a hard rule
# against acting under the wrong identity (CLAUDE.md §3 does this for GitHub), and
# the same failure mode exists for AWS: a stale `AWS_PROFILE` in a shell applies
# this configuration to whatever account that profile points at.
#
# IT FAILS CLOSED. `allowed_account_ids` has no default, so the binding must be
# supplied explicitly and must be twelve digits. Terraform refuses before any
# provider call if it is absent, and the provider refuses if the credentials
# resolve to a different account. An earlier revision defaulted to `[]`, which the
# provider reads as "no restriction" -- the guard was in the file and inactive.
#
# The value is an account identifier and is therefore NEVER committed: it belongs
# in the git-ignored `terraform.tfvars` or in `TF_VAR_allowed_account_ids`,
# alongside the credentials it guards.

provider "aws" {
  region              = var.aws_region
  allowed_account_ids = var.allowed_account_ids

  default_tags {
    tags = local.common_tags
  }
}
