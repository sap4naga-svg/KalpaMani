# The two ADR-0021 qualification runtime principals -- DECLARATIONS ONLY, APPLIED TO NOTHING.
#
# ADR-0021 is the gate PR #52 stopped in front of. That change merged the two
# qualification managed policies and deliberately named no holder for them, because
# accepted authority determined no runtime trust principal, and inventing an ECS,
# Lambda, EC2, federated or human principal inside a Terraform file would have been
# an architecture decision taken in the wrong place. ADR-0021 chose one: AWS IAM
# Identity Center permission-set roles, two permission sets, two governed profiles,
# one governed operator group.
#
# WHAT THIS FILE IS
#
#   Two `aws_ssoadmin_permission_set` declarations, one customer-managed-policy
#   reference each, and two group-principal account assignments. Nothing else.
#
# WHAT THIS FILE DELIBERATELY IS NOT
#
#   NO `aws_iam_role`. NO `assume_role_policy`. NO IAM user, access key, instance
#   profile, service principal, role chain or `sts:AssumeRole`. Identity Center
#   creates and manages the runtime role each assignment produces, and owns its
#   service trust; this repository authors no trust policy under that decision, and
#   a hand-written one would be a boundary KalpaMani then had to maintain instead of
#   one AWS makes unmodifiable.
#
#   NO INLINE POLICY. Each permission set references only the managed policy PR #52
#   already declared for its actor, by that resource's own name and path -- so the
#   two action matrices are referenced rather than restated, and neither can drift
#   from the policy it is meant to be.
#
#   NO LIVE DISCOVERY. There is no `aws_ssoadmin_instances`, no
#   `aws_identitystore_group` and no `aws_caller_identity` data source anywhere
#   here. Reading the live environment to write a declaration is the AWS form of
#   guessing, and every value this file needs from the environment is an input with
#   no default: a missing binding is a hard error before any provider call, which is
#   the fail-closed shape `allowed_account_ids` already has in providers.tf.
#
# WHAT IT DOES NOT TOUCH
#
#   No bucket, no bucket property, no KMS key, no encryption choice, no deletion
#   authority and no CONTROL authority. The two policy documents in
#   qualification_policies.tf are unchanged -- acquisition stays write-only and
#   assessment stays read-limited and report-write-limited -- and this file adds no
#   S3 action to either.
#
# APPLYING THIS IS A SEPARATE, UNGRANTED AUTHORIZATION. Declaring a permission set is
# not creating one, and an unapplied declaration grants no principal any AWS
# authority. Whether any live Identity Center instance, permission set, assignment or
# generated role exists is NOT ESTABLISHED here, because establishing it would take
# an AWS call that is not authorized.

variable "identity_center_instance_arn" {
  description = <<-EOT
    ARN of the governed IAM Identity Center instance the two permission sets are
    created in.

    NO DEFAULT, on purpose. A default would either be wrong everywhere, or would be
    a real environment binding committed to a public repository, and ADR-0021 keeps
    every Identity Center, identity-store, account, group, region and start-URL
    value unresolved and unread.

    The eventual deployment requires an ORGANIZATION instance with multi-account
    permissions enabled: an account instance provides neither permission sets nor
    account assignments. Whether such an instance exists is NOT ESTABLISHED, and it
    is checked only in a later authorized environment-discovery and binding gate.

    Supplied at apply time from an uncommitted `.tfvars` or `TF_VAR_` value.
  EOT
  type        = string

  validation {
    condition     = can(regex("^arn:aws:sso:::instance/[A-Za-z0-9-]{4,64}$", var.identity_center_instance_arn))
    error_message = "identity_center_instance_arn must be a commercial-partition Identity Center instance ARN."
  }
}

variable "qualification_operator_group_id" {
  description = <<-EOT
    Identity-store group id of the dedicated, governed qualification operator group
    that both permission sets are assigned to.

    NO DEFAULT. ADR-0021 makes the group assignment the authorization binding --
    authority travels group, then permission set, then assignment, then generated
    role, and there is no other path into the qualification permissions -- so a
    default here would be a default holder of the licensed-evidence permissions.

    The exact identity-store and group identifier is an environment-binding value and
    remains unknown and unread. The check below is structural only: it refuses an
    empty or whitespace-bearing value, and asserts nothing about which group the
    value names.
  EOT
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9-]{0,127}$", var.qualification_operator_group_id))
    error_message = "qualification_operator_group_id must be a non-empty identity-store group id with no whitespace."
  }
}

variable "qualification_target_account_id" {
  description = <<-EOT
    The single account that already owns the licensed data plane, and the only
    account the two permission sets are assigned in.

    NO DEFAULT, AND CROSS-CHECKED AGAINST THE PROVIDER BINDING. `allowed_account_ids`
    in providers.tf refuses to act with credentials for another account; it does not
    constrain where an assignment is TARGETED, so an assignment could otherwise be
    created against an account the wrong-account guard never looks at. The second
    validation closes that: the target must be one of the accounts this configuration
    is already bound to.

    The real value is an account identifier and is NEVER committed -- it goes in the
    git-ignored `terraform.tfvars`, or `TF_VAR_qualification_target_account_id`.
  EOT
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.qualification_target_account_id))
    error_message = "qualification_target_account_id must be exactly 12 decimal digits."
  }

  validation {
    condition     = contains(var.allowed_account_ids, var.qualification_target_account_id)
    error_message = "qualification_target_account_id must be one of allowed_account_ids; a target outside the provider binding would be assigned in an account the wrong-account guard never checks."
  }
}

locals {
  # The permission-set names, exactly as ADR-0022 accepts them. They are also the
  # `sso_role_name` an operator profile carries, and the role-name component the
  # identity gate matches against -- one spelling, in one place, so a rename cannot
  # leave the Terraform naming one role and the gate admitting another.
  #
  # The acquisition name is 29 characters. ADR-0021 accepted a 33-character one,
  # and the pinned provider validates this attribute to 1-32: that name could not
  # be built at all, so ADR-0022 retired it. The assessment name is 32 and is
  # unchanged. Both are measured against the provider's bounds by the repository's
  # own guards, because a limit stated only in prose is what let 33 through.
  qualification_acquisition_permission_set = "KalpaManiQualificationAcquire"
  qualification_assessment_permission_set  = "KalpaManiQualificationAssessment"

  # One hour. ADR-0021 bounds the session rather than raising it: it covers the
  # 1,800-second acquisition deadline with operational margin, and it is the AWS
  # default rather than an extension of one.
  qualification_session_duration = "PT1H"
}

# ---------------------------------------------------------------------------
# Acquisition -- the write-only actor
# ---------------------------------------------------------------------------

resource "aws_ssoadmin_permission_set" "qualification_acquisition" {
  name             = local.qualification_acquisition_permission_set
  description      = "ADR-0021 qualification acquisition actor: write-only licensed evidence publication. Not applied."
  instance_arn     = var.identity_center_instance_arn
  session_duration = local.qualification_session_duration

  tags = {
    Purpose = "qualification-acquisition"
  }
}

# The reference is taken from the merged policy resource rather than retyped, so the
# `name_prefix` that names the policy and the name this permission set attaches
# cannot drift, and Terraform orders the two without a `depends_on` to remember.
#
# A customer managed policy must already exist in the target account under the same
# name and path; that declaration is qualification_policies.tf, and applying either
# is a separate, ungranted authorization.
resource "aws_ssoadmin_customer_managed_policy_attachment" "qualification_acquisition" {
  instance_arn       = var.identity_center_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.qualification_acquisition.arn

  customer_managed_policy_reference {
    name = aws_iam_policy.qualification_acquisition.name
    path = aws_iam_policy.qualification_acquisition.path
  }
}

resource "aws_ssoadmin_account_assignment" "qualification_acquisition" {
  instance_arn       = var.identity_center_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.qualification_acquisition.arn

  principal_id   = var.qualification_operator_group_id
  principal_type = "GROUP"

  target_id   = var.qualification_target_account_id
  target_type = "AWS_ACCOUNT"
}

# ---------------------------------------------------------------------------
# Assessment -- the read-limited actor
# ---------------------------------------------------------------------------

resource "aws_ssoadmin_permission_set" "qualification_assessment" {
  name             = local.qualification_assessment_permission_set
  description      = "ADR-0021 qualification assessment actor: exact evidence reads and one private report. Not applied."
  instance_arn     = var.identity_center_instance_arn
  session_duration = local.qualification_session_duration

  tags = {
    Purpose = "qualification-assessment"
  }
}

resource "aws_ssoadmin_customer_managed_policy_attachment" "qualification_assessment" {
  instance_arn       = var.identity_center_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.qualification_assessment.arn

  customer_managed_policy_reference {
    name = aws_iam_policy.qualification_assessment.name
    path = aws_iam_policy.qualification_assessment.path
  }
}

# Two assignments, never one. ADR-0021 keeps the actors separate at the identity
# layer: one governed operator may hold both permission sets and must invoke each
# actor under its own profile, and no process ever holds the union of the two.
resource "aws_ssoadmin_account_assignment" "qualification_assessment" {
  instance_arn       = var.identity_center_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.qualification_assessment.arn

  principal_id   = var.qualification_operator_group_id
  principal_type = "GROUP"

  target_id   = var.qualification_target_account_id
  target_type = "AWS_ACCOUNT"
}
