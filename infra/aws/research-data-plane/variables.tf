# Input variables.
#
# NOTHING here carries a real account id, bucket name, email address, ARN,
# credential or any other owner-identifying value, and nothing here may ever be
# given one as a default. Identity-bearing values are supplied at apply time from
# an uncommitted `.tfvars` file -- see `terraform.tfvars.example`.

variable "name_prefix" {
  description = <<-EOT
    Prefix for every resource name. Deliberately has NO default: a default would
    be a name committed to a public repository, and S3 bucket names are globally
    visible in error messages and DNS.
  EOT
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$", var.name_prefix))
    error_message = "name_prefix must be 3-32 lowercase alphanumerics or hyphens, and may not start or end with a hyphen."
  }
}

variable "bucket_suffix" {
  description = <<-EOT
    Globally-unique suffix for S3 bucket names. S3 bucket names share one global
    namespace, so a suffix is required for creation to succeed at all.

    NO default, on purpose. Do not use anything derived from the owner's name,
    email, account id or the broker account -- a bucket name is not a secret and
    leaks in DNS, in error messages and in any shared log.
  EOT
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{2,20}[a-z0-9]$", var.bucket_suffix))
    error_message = "bucket_suffix must be 4-22 lowercase alphanumerics or hyphens, and may not start or end with a hyphen."
  }
}

variable "aws_region" {
  description = "Region for every resource. A generic default; no region reveals anything."
  type        = string
  default     = "us-east-1"
}

variable "allowed_account_ids" {
  description = <<-EOT
    Account ids this configuration may be applied to.

    NO DEFAULT, AND THAT IS THE CONTROL. An earlier revision defaulted to `[]`,
    which the AWS provider reads as "no restriction" -- so the guard against
    building KalpaMani in the wrong account was present in the file and inactive
    in practice. A safety control that is off unless someone remembers to switch
    it on is not a safety control; CLAUDE.md §3 already applies exactly this
    reasoning to GitHub accounts, and ADR-0003 to broker-side order controls.

    With no default, omitting it is a hard error before any provider call. The
    failure modes are therefore:

        no binding supplied  -> cannot plan or apply
        wrong account        -> the provider refuses
        intended account     -> eligible to continue

    The real value is an account identifier and is NEVER committed: it goes in
    the git-ignored `terraform.tfvars`, or `TF_VAR_allowed_account_ids`.
  EOT
  type        = list(string)

  validation {
    condition     = length(var.allowed_account_ids) >= 1
    error_message = "At least one AWS account id must be supplied. An empty list disables wrong-account protection, which is not permitted."
  }

  validation {
    condition     = alltrue([for id in var.allowed_account_ids : can(regex("^[0-9]{12}$", id))])
    error_message = "Each entry must be exactly 12 decimal digits. A placeholder or malformed id would silently disable the check."
  }
}

variable "vpc_cidr" {
  description = "CIDR for the research VPC. Private address space; reveals nothing."
  type        = string
  default     = "10.20.0.0/16"
}

variable "public_subnet_count" {
  description = <<-EOT
    Number of availability zones to place an egress-capable subnet in. Two gives
    a task somewhere to run if one AZ is unavailable; subnets themselves are free.
  EOT
  type        = number
  default     = 2

  validation {
    condition     = var.public_subnet_count >= 1 && var.public_subnet_count <= 4
    error_message = "public_subnet_count must be between 1 and 4."
  }
}

variable "log_retention_days" {
  description = <<-EOT
    CloudWatch Logs retention. Bounded on purpose: logs are a durable store, and
    an unbounded retention turns any redaction failure into a permanent one
    (ADR-0007 §8). "Never expire" is not offered as an option here.
  EOT
  type        = number
  default     = 30

  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365], var.log_retention_days)
    error_message = "log_retention_days must be one of the CloudWatch-supported values up to 365. Unbounded retention is not permitted."
  }
}

variable "multipart_abort_days" {
  description = <<-EOT
    Days after which an incomplete multipart upload is aborted automatically.

    This is a DELETION AID, not an archival lifecycle rule. Parts of an incomplete
    upload are stored and billed but do not appear in an object listing, so a
    list-and-delete deletion procedure would leave vendor bytes behind while
    reporting success (ADR-0007 §4; deletion runbook step 4).
  EOT
  type        = number
  default     = 7

  validation {
    condition     = var.multipart_abort_days >= 1 && var.multipart_abort_days <= 30
    error_message = "multipart_abort_days must be between 1 and 30."
  }
}

variable "untagged_image_expiry_days" {
  description = "Days after which an untagged ECR image is expired, to bound registry storage."
  type        = number
  default     = 14
}

variable "provider_secret_arns" {
  description = <<-EOT
    ARNs of Secrets Manager secrets / SSM SecureString parameters the research task
    role may READ at runtime.

    EMPTY BY DEFAULT, AND EMPTY IS THE CURRENT CORRECT VALUE. No provider has been
    selected (gate G1 is OPEN), no licence has been resolved (G3 is OPEN), no
    subscription has been purchased and no credential exists. This configuration
    creates NO secret and stores NO secret value; it records only the interface by
    which one would later be read.

    An ARN contains an account id, so this is supplied at apply time from an
    uncommitted `.tfvars` and is never committed.
  EOT
  type        = list(string)
  default     = []
}

variable "qualification_acquisition_secret_arns" {
  description = <<-EOT
    ARNs of the Secrets Manager secret holding the ONE governed provider credential
    the qualification acquisition actor may retrieve. This variable binds that
    credential to the qualification acquisition policy and to nothing else: the
    routine research task role reads `provider_secret_arns`, and the assessment
    actor reads no credential at all (ADR-0018 s.10.2).

    Separate from `provider_secret_arns` because the two are different grants to
    different principals. The routine task role's statement also carries the SSM
    parameter reads, so a single shared variable meant that binding the
    qualification credential silently re-scoped the routine research role as well.
    Populating this one changes the qualification acquisition policy only.

    EMPTY BY DEFAULT, AND EMPTY IS THE CURRENT CORRECT VALUE. No qualification run
    is authorized, so by default the acquisition policy grants no Secrets Manager
    access at all. This configuration creates NO secret and stores NO secret value;
    it records only the interface by which one would later be read.

    An ARN contains an account id, so this is supplied at apply time from an
    uncommitted `.tfvars`, is never committed, and binds this actor alone.
  EOT
  type        = list(string)
  default     = []
}
