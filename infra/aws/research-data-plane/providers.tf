# AWS provider configuration.
#
# `allowed_account_ids` is the guard that matters here. KalpaMani has a hard rule
# against acting under the wrong identity (CLAUDE.md §3 does this for GitHub), and
# the same failure mode exists for AWS: a stale `AWS_PROFILE` in a shell applies
# this configuration to whatever account that profile points at.
#
# Supplying the id makes the provider refuse rather than proceed. The value is an
# account identifier and is therefore NEVER committed -- it belongs in an
# uncommitted `.tfvars` or an environment variable, alongside the credentials it
# guards. The default is empty, which disables the check; setting it is strongly
# recommended before any apply is authorized.

provider "aws" {
  region              = var.aws_region
  allowed_account_ids = var.allowed_account_ids

  default_tags {
    tags = local.common_tags
  }
}
