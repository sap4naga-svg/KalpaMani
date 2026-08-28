# Shared locals and lookups.
#
# There are no resources in this file. Resources live in the file named after the
# thing they create: storage.tf, iam.tf, network.tf, ecr.tf, ecs.tf, logging.tf.

data "aws_availability_zones" "available" {
  state = "available"

  # Opt-in regions require explicit account enablement; excluding them keeps a
  # plan from failing on an AZ the account cannot use.
  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

# Resolved at apply time from the caller's credentials. Used only to scope IAM
# trust conditions. The value is an account id, so it is never written into any
# committed file -- it lives in state, which is git-ignored.
data "aws_caller_identity" "current" {}

locals {
  # Tags carry no owner-identifying information. `DataClass` is the important one:
  # it makes the licensed/control boundary visible in the console and in Cost
  # Explorer, and it is what a deletion procedure filters on.
  common_tags = {
    Project   = "KalpaMani"
    Component = "research-data-plane"
    ManagedBy = "terraform"
    Phase     = "phase-3-planning"
  }

  licensed_bucket_name = "${var.name_prefix}-licensed-${var.bucket_suffix}"
  control_bucket_name  = "${var.name_prefix}-control-${var.bucket_suffix}"

  availability_zones = slice(
    data.aws_availability_zones.available.names,
    0,
    min(var.public_subnet_count, length(data.aws_availability_zones.available.names))
  )
}
