# ADR-0036 production data-plane principals -- THE INPUTS, AND THE STAGE GATE.
#
# Every ADR-0036 declaration in the `production_*.tf` files is gated on
# `production_stage`, and the default stage is `none`: with the committed defaults
# this configuration declares NOTHING new and changes NOTHING already applied.
# That is what lets an offline candidate merge without moving a deployed resource
# -- the foundation and the qualification package plan to no change until an
# owner-supplied `.tfvars` value moves the stage, under its own authorization.
#
# ADR-0036 s.2.7 and s.3 make application a TWO-STAGE sequence:
#
#   stage a   policies, bucket-policy statements, task roles, bootstrap policies,
#             the KMS key, the binding parameters, the network, the task
#             definitions, the permission sets and their policy references --
#             everything that can exist without any principal being able to use it.
#             No account assignment. No launcher assignment.
#   R-3       the live server-side conditional-write verification (ADR-0036 s.3),
#             run by the control principal against stage a. Not Terraform.
#   stage b   the four account assignments, and nothing else -- reachable ONLY when
#             the R-3 verification record is named below.
#
# Stage b cannot be selected without `production_r3_verification_digest`, and
# Terraform enforces that before any provider call. The digest is the SHA-256 of
# the owner's R-3 verification record; supplying it is the owner's written
# statement that R-3 was verified, and Terraform checks only that a statement was
# made, not that it is true -- that is the owner's, under ADR-0036 s.2.7.
#
# NOTHING HERE HAS A REAL VALUE. Every identifier-bearing input has no default and
# is supplied from the git-ignored `terraform.tfvars`. Declaring is not applying.

variable "production_stage" {
  description = <<-EOT
    Which ADR-0036 application stage this configuration declares.

      none   (default) -- declare nothing new; every production resource has count 0
      a      -- policies, roles, key, bindings, network, task definitions, permission
                sets; NO assignments, so no principal can use any of it
      b      -- stage a plus the four account assignments; requires the R-3
                verification digest below

    Moving the stage is a separately authorized `terraform apply`, never a default.
  EOT
  type        = string
  default     = "none"

  validation {
    condition     = contains(["none", "a", "b"], var.production_stage)
    error_message = "production_stage must be one of: none, a, b."
  }

  validation {
    condition     = var.production_stage != "b" || can(regex("^[0-9a-f]{64}$", var.production_r3_verification_digest))
    error_message = "production_stage b requires production_r3_verification_digest: the SHA-256 of the owner's R-3 verification record (ADR-0036 s.2.7, s.3). No assignment is declared until R-3 is verified."
  }
}

variable "production_r3_verification_digest" {
  description = <<-EOT
    SHA-256 (64 lowercase hex) of the owner's R-3 verification record -- the
    record that the server-side conditional-write refusal was demonstrated with a
    fresh positive control and attributed to the bucket policy (ADR-0036 s.3).

    EMPTY BY DEFAULT. Required only for `production_stage = "b"`. A digest is not
    an identifier and is not a secret, but it is the owner's evidence pointer and
    lives in the uncommitted `.tfvars` with everything else.
  EOT
  type        = string
  default     = ""

  validation {
    condition     = var.production_r3_verification_digest == "" || can(regex("^[0-9a-f]{64}$", var.production_r3_verification_digest))
    error_message = "production_r3_verification_digest must be empty or 64 lowercase hex characters."
  }
}

variable "production_target_account_id" {
  description = <<-EOT
    The single account that owns the licensed data plane and receives the four
    ADR-0036 account assignments. ADR-0036 s.2.1 puts production in the SAME
    account as qualification, so when this is unset it takes the value of
    `qualification_target_account_id` -- one binding, not two that can disagree.

    When set, it must be one of `allowed_account_ids`, for the reason
    `qualification_target_account_id` gives: the provider binding constrains
    whose credentials act, not where an assignment is targeted.

    An account identifier: NEVER committed.
  EOT
  type        = string
  default     = null

  validation {
    condition     = var.production_target_account_id == null || can(regex("^[0-9]{12}$", var.production_target_account_id))
    error_message = "production_target_account_id must be exactly 12 decimal digits when set."
  }

  validation {
    condition     = var.production_target_account_id == null || contains(var.allowed_account_ids, var.production_target_account_id)
    error_message = "production_target_account_id must be one of allowed_account_ids."
  }
}

variable "production_acquisition_secret_arn" {
  description = <<-EOT
    ARN of the ONE Secrets Manager secret holding the production Sharadar
    credential -- the acquisition actor's only secret, and a DIFFERENT resource
    from the qualification secret (ADR-0036 s.2.2). Its own variable, for the reason
    `qualification_acquisition_secret_arns` has its own: one variable per principal,
    so populating one cannot re-scope another.

    EMPTY BY DEFAULT and required for any stage other than `none`: an acquisition
    actor with no secret to name is not declared at all. An ARN contains an account
    id and is never committed. This configuration creates NO secret.
  EOT
  type        = string
  default     = ""

  validation {
    condition     = var.production_acquisition_secret_arn == "" || can(regex("^arn:aws:secretsmanager:[a-z0-9-]+:[0-9]{12}:secret:[A-Za-z0-9/_+=.@-]+$", var.production_acquisition_secret_arn))
    error_message = "production_acquisition_secret_arn must be a commercial-partition Secrets Manager secret ARN."
  }

  validation {
    condition     = var.production_stage == "none" || var.production_acquisition_secret_arn != ""
    error_message = "production_stage a or b requires production_acquisition_secret_arn."
  }
}

variable "production_image_digests" {
  description = <<-EOT
    The image digests the two task definitions pin, by actor: keys `acquisition`
    and `build`, values `sha256:<64 hex>`. ADR-0036 s.2.9: an image is pinned BY
    DIGEST, never by tag, so a registered revision names one exact image.

    EMPTY BY DEFAULT and required, with both keys, for any stage other than `none`.
    A digest is not an identifier; it is nevertheless supplied at apply time,
    because no production image exists until an image gate builds one.
  EOT
  type        = map(string)
  default     = {}

  validation {
    condition = alltrue([
      for digest in values(var.production_image_digests) : can(regex("^sha256:[0-9a-f]{64}$", digest))
    ])
    error_message = "every production_image_digests value must be sha256:<64 lowercase hex>."
  }

  validation {
    condition     = var.production_stage == "none" || (contains(keys(var.production_image_digests), "acquisition") && contains(keys(var.production_image_digests), "build"))
    error_message = "production_stage a or b requires production_image_digests with keys acquisition and build."
  }
}

variable "production_binding_provenance" {
  description = <<-EOT
    The ADR-0023 provenance block written into the two task runtime-binding
    parameters (ADR-0036 s.2.5): the implementation commit and tree the binding
    was materialized against, and the environment-binding digest. Shape-checked
    here exactly as the loader checks it.

    NULL BY DEFAULT and required for any stage other than `none`. These are
    private operational metadata, not secrets; they are supplied at apply time and
    never committed.
  EOT
  type = object({
    implementation_commit      = string
    implementation_tree        = string
    environment_binding_sha256 = string
  })
  default = null

  validation {
    condition = var.production_binding_provenance == null || (
      can(regex("^[0-9a-f]{40}$", var.production_binding_provenance.implementation_commit)) &&
      can(regex("^[0-9a-f]{40}$", var.production_binding_provenance.implementation_tree)) &&
      can(regex("^[0-9a-f]{64}$", var.production_binding_provenance.environment_binding_sha256))
    )
    error_message = "production_binding_provenance fields must be 40/40/64 lowercase hex characters."
  }

  validation {
    condition     = var.production_stage == "none" || var.production_binding_provenance != null
    error_message = "production_stage a or b requires production_binding_provenance."
  }
}

variable "production_provider_origin_cidrs" {
  description = <<-EOT
    The provider origin's resolved IPv4 address set, as CIDR blocks, materialized
    at the Terraform gate and refreshed before each authorized run window
    (ADR-0036 s.2.8). The acquisition security group's only non-AWS egress.

    This is an ADDRESS restriction, not a hostname restriction, and the ADR says
    so; the hostname pin is the transport's. EMPTY BY DEFAULT and required
    non-empty for any stage other than `none`: an acquisition subnet with nowhere
    to send a request is declared with no provider rule at all rather than with an
    open one.
  EOT
  type        = list(string)
  default     = []

  validation {
    condition = alltrue([
      for cidr in var.production_provider_origin_cidrs : can(cidrnetmask(cidr))
    ])
    error_message = "every production_provider_origin_cidrs entry must be an IPv4 CIDR block."
  }

  validation {
    condition     = !contains(var.production_provider_origin_cidrs, "0.0.0.0/0")
    error_message = "production_provider_origin_cidrs must not contain 0.0.0.0/0: the allowlist would then be no allowlist."
  }

  validation {
    condition     = var.production_stage == "none" || length(var.production_provider_origin_cidrs) > 0
    error_message = "production_stage a or b requires at least one provider origin CIDR."
  }
}

variable "identity_center_region" {
  description = <<-EOT
    The AWS Region the governed IAM Identity Center instance is hosted in -- NOT
    the workload region `aws_region`, which may differ. It selects the shape of
    every generated permission-set role ARN this configuration matches in a key
    policy: AWS documents that when Identity Center is hosted in us-east-1 the
    role ARN carries NO region path element
    (`role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_<name>_<suffix>`), and in
    every other Region it carries one
    (`role/aws-reserved/sso.amazonaws.com/<region>/AWSReservedSSO_<name>_<suffix>`).
    The pattern is derived from this value, so neither shape is guessed.

    NULL BY DEFAULT and required for any stage other than `none`. A Region name
    is not an identifier, but which Region hosts the instance is an environment
    binding and is supplied at apply time with the other bindings.
  EOT
  type        = string
  default     = null

  validation {
    condition     = var.identity_center_region == null || can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]$", var.identity_center_region))
    error_message = "identity_center_region must be an AWS Region name such as us-east-1 or eu-west-2."
  }

  validation {
    condition     = var.production_stage == "none" || var.identity_center_region != null
    error_message = "production_stage a or b requires identity_center_region: the generated-role ARN shape depends on it."
  }
}

variable "production_endpoints_enabled" {
  description = <<-EOT
    Whether the six interface VPC endpoints (ecr.api, ecr.dkr, logs, ssm, sts,
    secretsmanager) are declared. They bill hourly while they exist (ADR-0036
    s.2.8, s.4), so this toggle lets them exist only during authorized run windows.
    Each toggle is an apply under its own authorization. FALSE BY DEFAULT, and
    meaningless at stage `none`.
  EOT
  type        = bool
  default     = false
}

variable "production_apply_principal_arn_pattern" {
  description = <<-EOT
    `aws:PrincipalArn` pattern (StringLike) of the Terraform-apply principal that
    administers the task-bindings KMS key and materializes the two binding
    parameters (ADR-0036 s.2.5 key-policy table). An Identity Center generated
    role rotates its suffix, so this is a PATTERN, matched by prefix, never a full
    ARN -- the same stance ADR-0021 takes for every generated role.

    EMPTY BY DEFAULT and required for any stage other than `none`. Contains an
    account id: never committed.
  EOT
  type        = string
  default     = ""

  validation {
    condition     = var.production_apply_principal_arn_pattern == "" || can(regex("^arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/*-]+$", var.production_apply_principal_arn_pattern))
    error_message = "production_apply_principal_arn_pattern must be an IAM role ARN pattern in the commercial partition."
  }

  validation {
    condition     = var.production_stage == "none" || var.production_apply_principal_arn_pattern != ""
    error_message = "production_stage a or b requires production_apply_principal_arn_pattern."
  }
}

locals {
  # The stage gate, as counts. Every ADR-0036 resource carries one of these two;
  # a resource carrying neither is a resource that would exist at stage `none`,
  # and the static guard refuses it.
  production_stage_a = contains(["a", "b"], var.production_stage)
  production_stage_b = var.production_stage == "b"
  production_count_a = local.production_stage_a ? 1 : 0
  production_count_b = local.production_stage_b ? 1 : 0

  # One account, one operator group, shared with qualification by ADR-0036 s.2.1
  # and s.2.9: the same governed group holds every permission set, and the actors
  # are separated by permission set and profile, never by group.
  production_target_account_id = coalesce(var.production_target_account_id, var.qualification_target_account_id)
  production_operator_group_id = var.qualification_operator_group_id

  # Account consistency (a BLOCKING precondition, enforced by
  # production_principals.tf on the guard resource and on every assignment):
  # the account the provider actually acts in, the production target the
  # bindings, parameter ARNs and assignments name, and the qualification target
  # must be one account. `allowed_account_ids` constrains only the first;
  # a target inside that list but different from the caller would otherwise be
  # written into bindings and assignments for an account the credentials never
  # act in. Evaluated only where a stage-a resource exists, so stage `none`
  # stays inert.
  production_account_consistent = (
    local.production_target_account_id == data.aws_caller_identity.current.account_id
    && local.production_target_account_id == var.qualification_target_account_id
  )

  # The generated permission-set role ARN path (ADR-0036 s.2.5; AWS Identity
  # Center documentation): regionless when the instance is hosted in us-east-1,
  # regional otherwise. Empty when the region is unset (stage none), where no
  # key policy is declared.
  production_sso_role_path = (
    var.identity_center_region == null || var.identity_center_region == "us-east-1"
    ? "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_"
    : "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/aws-reserved/sso.amazonaws.com/${var.identity_center_region}/AWSReservedSSO_"
  )
}
