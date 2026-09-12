# ADR-0036 production principals -- OFFLINE Terraform tests with a MOCK provider.
#
# `terraform test` with `mock_provider "aws"` evaluates the configuration's own
# logic -- variable validation, locals, preconditions, counts -- against a provider
# that returns synthetic values and reaches nothing. No credential is read, no
# account is contacted, no resource exists before or after. It is run from a
# task-owned external copy of the configuration (`terraform test
# -test-directory=<this directory>`), never against the repository directory.
#
# What these cases prove: that the configuration REFUSES the inputs it must refuse
# and DECLARES what it must at each stage. What they do not prove: anything about
# AWS -- that a policy is honoured, that a key can be administered, that a task
# starts. Those are ADR-0036's layers L2/L3.
#
# Every account id, ARN and digest below is synthetic and deliberately shaped so
# that it cannot be a real binding: repeated digits, and hex made of one letter.
# This file lives outside `infra/`, where committed files may carry no
# twelve-digit value at all.

mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "111111111111"
      arn        = "arn:aws:iam::111111111111:root"
      user_id    = "AIDAMOCKMOCKMOCKMOCK1"
    }
  }

  mock_data "aws_availability_zones" {
    defaults = {
      names = ["us-east-1a", "us-east-1b"]
    }
  }

  # A policy document's `json` is provider-computed; the mock must hand back a
  # JSON object or every role, key and endpoint that embeds one refuses it.
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
}

variables {
  name_prefix                     = "mock-kalpamani-research"
  bucket_suffix                   = "mocksuffix"
  aws_region                      = "us-east-1"
  allowed_account_ids             = ["111111111111", "222222222222"]
  identity_center_instance_arn    = "arn:aws:sso:::instance/ssoins-mockmockmockmock"
  qualification_operator_group_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
  qualification_target_account_id = "111111111111"
}

# ---------------------------------------------------------------------------
# Stage none: valid, and inert
# ---------------------------------------------------------------------------

run "stage_none_declares_nothing" {
  command = plan

  assert {
    condition     = length(aws_iam_policy.production_acquisition) == 0 && length(aws_iam_policy.production_build) == 0
    error_message = "stage none must declare no production policy"
  }

  assert {
    condition     = length(aws_iam_role.production_acquire_task) == 0 && length(aws_iam_role.production_build_task) == 0
    error_message = "stage none must declare no production task role"
  }

  assert {
    condition     = length(aws_ssoadmin_account_assignment.production_acquisition) == 0 && length(aws_ssoadmin_account_assignment.production_build_launcher) == 0
    error_message = "stage none must declare no assignment"
  }

  assert {
    condition     = length(terraform_data.production_account_guard) == 0
    error_message = "stage none must evaluate no account guard"
  }

  assert {
    condition     = length(aws_vpc_endpoint.production_secretsmanager) == 0 && length(aws_vpc_endpoint.production_interface) == 0
    error_message = "stage none must declare no endpoint"
  }
}

# ---------------------------------------------------------------------------
# Stage a: every required input, matching accounts -> declared, no assignment
# ---------------------------------------------------------------------------

run "stage_a_with_matching_accounts_declares_without_assignments" {
  command = plan

  variables {
    production_stage                       = "a"
    identity_center_region                 = "us-east-1"
    production_acquisition_secret_arn      = "arn:aws:secretsmanager:us-east-1:111111111111:secret:mock-production-secret-AbCdEf"
    production_apply_principal_arn_pattern = "arn:aws:iam::111111111111:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_MockAdmin_*"
    production_image_digests = {
      acquisition = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      build       = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    }
    production_binding_provenance = {
      implementation_commit      = "cccccccccccccccccccccccccccccccccccccccc"
      implementation_tree        = "dddddddddddddddddddddddddddddddddddddddd"
      environment_binding_sha256 = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    }
    production_provider_origin_cidrs = ["203.0.113.0/24"]
    production_endpoints_enabled     = true
  }

  assert {
    condition     = length(aws_iam_policy.production_acquisition) == 1 && length(aws_iam_role.production_acquire_task) == 1
    error_message = "stage a must declare the acquisition policy and task role"
  }

  assert {
    condition     = length(aws_ssoadmin_account_assignment.production_acquisition) == 0 && length(aws_ssoadmin_account_assignment.production_acquire_launcher) == 0
    error_message = "stage a must declare NO assignment"
  }

  assert {
    condition     = local.production_account_consistent
    error_message = "matching accounts must satisfy the account guard"
  }

  # Finding 5: Identity Center in us-east-1 -> the REGIONLESS role-ARN path.
  assert {
    condition     = local.production_sso_role_path == "arn:aws:iam::111111111111:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_"
    error_message = "us-east-1 Identity Center must yield the regionless generated-role path"
  }

  # Finding 2: the Secrets Manager endpoint is separate, on its own security group.
  assert {
    condition     = length(aws_vpc_endpoint.production_secretsmanager) == 1 && !contains(keys(aws_vpc_endpoint.production_interface), "secretsmanager")
    error_message = "Secrets Manager must be its own endpoint, not one of the shared five"
  }

  assert {
    condition     = length(aws_vpc_endpoint.production_interface) == 5
    error_message = "exactly five shared interface endpoints"
  }
}

# ---------------------------------------------------------------------------
# Finding 5: Identity Center outside us-east-1 -> the REGIONAL role-ARN path
# ---------------------------------------------------------------------------

run "regional_identity_center_yields_regional_role_path" {
  command = plan

  variables {
    production_stage                       = "a"
    identity_center_region                 = "eu-west-2"
    production_acquisition_secret_arn      = "arn:aws:secretsmanager:us-east-1:111111111111:secret:mock-production-secret-AbCdEf"
    production_apply_principal_arn_pattern = "arn:aws:iam::111111111111:role/aws-reserved/sso.amazonaws.com/eu-west-2/AWSReservedSSO_MockAdmin_*"
    production_image_digests = {
      acquisition = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      build       = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    }
    production_binding_provenance = {
      implementation_commit      = "cccccccccccccccccccccccccccccccccccccccc"
      implementation_tree        = "dddddddddddddddddddddddddddddddddddddddd"
      environment_binding_sha256 = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    }
    production_provider_origin_cidrs = ["203.0.113.0/24"]
  }

  assert {
    condition     = local.production_sso_role_path == "arn:aws:iam::111111111111:role/aws-reserved/sso.amazonaws.com/eu-west-2/AWSReservedSSO_"
    error_message = "a non-us-east-1 Identity Center must yield the regional generated-role path, using the Identity Center region and not the workload region"
  }
}

run "stage_a_requires_the_identity_center_region" {
  command = plan

  variables {
    production_stage                       = "a"
    production_acquisition_secret_arn      = "arn:aws:secretsmanager:us-east-1:111111111111:secret:mock-production-secret-AbCdEf"
    production_apply_principal_arn_pattern = "arn:aws:iam::111111111111:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_MockAdmin_*"
    production_image_digests = {
      acquisition = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      build       = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    }
    production_binding_provenance = {
      implementation_commit      = "cccccccccccccccccccccccccccccccccccccccc"
      implementation_tree        = "dddddddddddddddddddddddddddddddddddddddd"
      environment_binding_sha256 = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    }
    production_provider_origin_cidrs = ["203.0.113.0/24"]
  }

  expect_failures = [var.identity_center_region]
}

# ---------------------------------------------------------------------------
# Finding 4: account consistency is a BLOCKING precondition
# ---------------------------------------------------------------------------

# The target is in allowed_account_ids -- and is not the account the provider acts in.
run "mismatched_target_inside_allowed_accounts_blocks_stage_a" {
  command = plan

  variables {
    production_stage                       = "a"
    identity_center_region                 = "us-east-1"
    production_target_account_id           = "222222222222"
    qualification_target_account_id        = "222222222222"
    production_acquisition_secret_arn      = "arn:aws:secretsmanager:us-east-1:222222222222:secret:mock-production-secret-AbCdEf"
    production_apply_principal_arn_pattern = "arn:aws:iam::222222222222:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_MockAdmin_*"
    production_image_digests = {
      acquisition = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      build       = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    }
    production_binding_provenance = {
      implementation_commit      = "cccccccccccccccccccccccccccccccccccccccc"
      implementation_tree        = "dddddddddddddddddddddddddddddddddddddddd"
      environment_binding_sha256 = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    }
    production_provider_origin_cidrs = ["203.0.113.0/24"]
  }

  expect_failures = [terraform_data.production_account_guard]
}

# The production target differs from the qualification target (same-account
# relationship broken), even though it equals the provider account.
run "production_target_differing_from_qualification_target_blocks_stage_a" {
  command = plan

  variables {
    production_stage                       = "a"
    identity_center_region                 = "us-east-1"
    production_target_account_id           = "111111111111"
    qualification_target_account_id        = "222222222222"
    production_acquisition_secret_arn      = "arn:aws:secretsmanager:us-east-1:111111111111:secret:mock-production-secret-AbCdEf"
    production_apply_principal_arn_pattern = "arn:aws:iam::111111111111:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_MockAdmin_*"
    production_image_digests = {
      acquisition = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      build       = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    }
    production_binding_provenance = {
      implementation_commit      = "cccccccccccccccccccccccccccccccccccccccc"
      implementation_tree        = "dddddddddddddddddddddddddddddddddddddddd"
      environment_binding_sha256 = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    }
    production_provider_origin_cidrs = ["203.0.113.0/24"]
  }

  expect_failures = [terraform_data.production_account_guard]
}

# A target outside allowed_account_ids is refused earlier, by the variable itself.
run "target_outside_allowed_accounts_is_refused_by_the_variable" {
  command = plan

  variables {
    production_stage             = "none"
    production_target_account_id = "333333333333"
  }

  expect_failures = [var.production_target_account_id]
}

# ---------------------------------------------------------------------------
# Stage b: refused without the R-3 digest; declares the four assignments with it
# ---------------------------------------------------------------------------

run "stage_b_without_the_r3_digest_is_refused" {
  command = plan

  variables {
    production_stage                       = "b"
    identity_center_region                 = "us-east-1"
    production_acquisition_secret_arn      = "arn:aws:secretsmanager:us-east-1:111111111111:secret:mock-production-secret-AbCdEf"
    production_apply_principal_arn_pattern = "arn:aws:iam::111111111111:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_MockAdmin_*"
    production_image_digests = {
      acquisition = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      build       = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    }
    production_binding_provenance = {
      implementation_commit      = "cccccccccccccccccccccccccccccccccccccccc"
      implementation_tree        = "dddddddddddddddddddddddddddddddddddddddd"
      environment_binding_sha256 = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    }
    production_provider_origin_cidrs = ["203.0.113.0/24"]
  }

  expect_failures = [var.production_stage]
}

run "stage_b_with_the_r3_digest_declares_the_four_assignments" {
  command = plan

  variables {
    production_stage                       = "b"
    production_r3_verification_digest      = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    identity_center_region                 = "us-east-1"
    production_acquisition_secret_arn      = "arn:aws:secretsmanager:us-east-1:111111111111:secret:mock-production-secret-AbCdEf"
    production_apply_principal_arn_pattern = "arn:aws:iam::111111111111:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_MockAdmin_*"
    production_image_digests = {
      acquisition = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      build       = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    }
    production_binding_provenance = {
      implementation_commit      = "cccccccccccccccccccccccccccccccccccccccc"
      implementation_tree        = "dddddddddddddddddddddddddddddddddddddddd"
      environment_binding_sha256 = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    }
    production_provider_origin_cidrs = ["203.0.113.0/24"]
  }

  assert {
    condition = (
      length(aws_ssoadmin_account_assignment.production_acquisition) == 1
      && length(aws_ssoadmin_account_assignment.production_build) == 1
      && length(aws_ssoadmin_account_assignment.production_acquire_launcher) == 1
      && length(aws_ssoadmin_account_assignment.production_build_launcher) == 1
    )
    error_message = "stage b with the digest must declare exactly the four assignments"
  }
}

# A digest of the wrong shape is refused by its own variable.
run "a_malformed_r3_digest_is_refused" {
  command = plan

  variables {
    production_stage                  = "none"
    production_r3_verification_digest = "not-a-digest"
  }

  expect_failures = [var.production_r3_verification_digest]
}

# ---------------------------------------------------------------------------
# The provider allowlist refuses 0.0.0.0/0 at the variable
# ---------------------------------------------------------------------------

run "an_open_provider_cidr_is_refused" {
  command = plan

  variables {
    production_stage                 = "none"
    production_provider_origin_cidrs = ["0.0.0.0/0"]
  }

  expect_failures = [var.production_provider_origin_cidrs]
}
