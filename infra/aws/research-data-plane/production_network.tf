# ADR-0036 production data-plane principals -- THE NETWORK.
#
# The foundation VPC (network.tf) is public subnets behind an internet gateway, a
# task security group with no inbound rule and `0.0.0.0/0:443` egress, and no VPC
# endpoint. ADR-0036 s.2.8 adds what the two actors need and nothing more:
#
#   build subnet       NEW, private: no route to the internet gateway, no NAT. Its
#                      route table carries the local route and the S3 gateway prefix
#                      list. Provider unreachability is a property of routing and
#                      rules, not of application restraint.
#   acquisition        the EXISTING first public subnet -- a public IP is what makes
#                      the provider reachable without a NAT gateway (ADR-0007 s.6) --
#                      with a NEW security group whose egress is an allowlist: the S3
#                      prefix list, the endpoint security group, and the provider
#                      origin's address set supplied at apply time. NO 0.0.0.0/0.
#   endpoints          one S3 gateway endpoint (no hourly charge) whose policy admits
#                      the licensed bucket and the ECR layer bucket only; six
#                      interface endpoints (hourly-billed) behind a toggle, so they
#                      exist only during authorized run windows.
#
# The address allowlist is an ADDRESS restriction, not a hostname restriction
# (ADR-0036 s.2.8): a security group cannot see TLS SNI. The hostname pin is the
# transport's. AWS Network Firewall is the named upgrade path and is NOT declared.
#
# Nothing in network.tf changes. The existing task security group and public route
# table are referenced, never edited; the S3 gateway endpoint associates with the
# public route table only when stage a exists.

locals {
  # Subnet index 250 of the /16: far from the public subnets at 0..count-1, and
  # deterministic. `cidrsubnet(var.vpc_cidr, 8, 250)` is `<vpc>.250.0/24`.
  production_build_subnet_index = 250

  production_interface_endpoints = var.production_endpoints_enabled && local.production_stage_a ? toset([
    "ecr.api",
    "ecr.dkr",
    "logs",
    "ssm",
    "sts",
    "secretsmanager",
  ]) : toset([])

  # Egress to AWS services goes through the endpoints; DNS goes to the VPC
  # resolver, which lives inside the VPC CIDR (network.tf explains why).
  production_vpc_resolver_cidr = var.vpc_cidr
}

# ---------------------------------------------------------------------------
# Build subnet -- private, and routed nowhere but locally and to S3
# ---------------------------------------------------------------------------

resource "aws_subnet" "production_build" {
  count = local.production_count_a

  vpc_id            = aws_vpc.research.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, local.production_build_subnet_index)
  availability_zone = local.availability_zones[0]

  # Never a public IP: there is no gateway to route one through anyway.
  map_public_ip_on_launch = false

  tags = {
    Name    = "${var.name_prefix}-production-build"
    Purpose = "production-build"
  }
}

# A route table with NO `route` block: the implicit local route is the whole of
# it, and the S3 gateway endpoint adds its prefix-list route by association.
# There is no `0.0.0.0/0`, and a test asserts that on the parsed file.
resource "aws_route_table" "production_build" {
  count = local.production_count_a

  vpc_id = aws_vpc.research.id

  tags = {
    Name    = "${var.name_prefix}-production-build"
    Purpose = "production-build"
  }
}

resource "aws_route_table_association" "production_build" {
  count = local.production_count_a

  subnet_id      = aws_subnet.production_build[0].id
  route_table_id = aws_route_table.production_build[0].id
}

# ---------------------------------------------------------------------------
# S3 gateway endpoint -- the licensed bucket and the ECR layer bucket, nothing else
# ---------------------------------------------------------------------------
#
# Fargate pulls image layers from a regional S3 bucket AWS owns
# (`prod-<region>-starport-layer-bucket`); the endpoint policy names it and the
# licensed bucket, so a task on either subnet can reach no other bucket through
# this path even before its identity policy is consulted.

data "aws_iam_policy_document" "production_s3_endpoint" {
  statement {
    sid    = "LicensedBucketAndEcrLayersOnly"
    effect = "Allow"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.licensed.arn,
      "${aws_s3_bucket.licensed.arn}/*",
      "arn:aws:s3:::prod-${var.aws_region}-starport-layer-bucket/*",
    ]
  }
}

resource "aws_vpc_endpoint" "production_s3" {
  count = local.production_count_a

  vpc_id            = aws_vpc.research.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  policy            = data.aws_iam_policy_document.production_s3_endpoint.json

  route_table_ids = [
    aws_route_table.production_build[0].id,
    aws_route_table.public.id,
  ]

  tags = {
    Name    = "${var.name_prefix}-production-s3"
    Purpose = "production-network"
  }
}

# ---------------------------------------------------------------------------
# Interface endpoints -- hourly-billed, toggled, and the only AWS path for the build
# ---------------------------------------------------------------------------

resource "aws_security_group" "production_endpoints" {
  count = local.production_count_a

  name        = "${var.name_prefix}-production-endpoints"
  description = "Interface endpoints for the ADR-0036 tasks. Admits 443 from the two task security groups only."
  vpc_id      = aws_vpc.research.id

  tags = {
    Name    = "${var.name_prefix}-production-endpoints"
    Purpose = "production-network"
  }
}

resource "aws_vpc_security_group_ingress_rule" "production_endpoints_from_build" {
  count = local.production_count_a

  security_group_id            = aws_security_group.production_endpoints[0].id
  description                  = "HTTPS from the build task security group."
  referenced_security_group_id = aws_security_group.production_build[0].id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}

resource "aws_vpc_security_group_ingress_rule" "production_endpoints_from_acquisition" {
  count = local.production_count_a

  security_group_id            = aws_security_group.production_endpoints[0].id
  description                  = "HTTPS from the acquisition task security group."
  referenced_security_group_id = aws_security_group.production_acquisition[0].id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}

resource "aws_vpc_endpoint" "production_interface" {
  for_each = local.production_interface_endpoints

  vpc_id              = aws_vpc.research.id
  service_name        = "com.amazonaws.${var.aws_region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = [aws_subnet.production_build[0].id]
  security_group_ids  = [aws_security_group.production_endpoints[0].id]

  tags = {
    Name    = "${var.name_prefix}-production-${replace(each.key, ".", "-")}"
    Purpose = "production-network"
  }
}

# ---------------------------------------------------------------------------
# Build task security group -- S3 prefix list, the endpoints, DNS; nothing else
# ---------------------------------------------------------------------------

resource "aws_security_group" "production_build" {
  count = local.production_count_a

  name        = "${var.name_prefix}-production-build-task"
  description = "ADR-0036 build task egress: S3 gateway, interface endpoints, VPC DNS. No inbound rule exists."
  vpc_id      = aws_vpc.research.id

  # THERE IS NO `ingress` BLOCK, AND NO 0.0.0.0/0 EGRESS RULE BELOW.

  tags = {
    Name    = "${var.name_prefix}-production-build-task"
    Purpose = "production-build"
  }
}

resource "aws_vpc_security_group_egress_rule" "production_build_s3" {
  count = local.production_count_a

  security_group_id = aws_security_group.production_build[0].id
  description       = "HTTPS to S3 through the gateway endpoint's prefix list."
  prefix_list_id    = aws_vpc_endpoint.production_s3[0].prefix_list_id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_egress_rule" "production_build_endpoints" {
  count = local.production_count_a

  security_group_id            = aws_security_group.production_build[0].id
  description                  = "HTTPS to the interface endpoints."
  referenced_security_group_id = aws_security_group.production_endpoints[0].id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}

resource "aws_vpc_security_group_egress_rule" "production_build_dns_udp" {
  count = local.production_count_a

  security_group_id = aws_security_group.production_build[0].id
  description       = "DNS to the VPC resolver."
  cidr_ipv4         = local.production_vpc_resolver_cidr
  ip_protocol       = "udp"
  from_port         = 53
  to_port           = 53
}

resource "aws_vpc_security_group_egress_rule" "production_build_dns_tcp" {
  count = local.production_count_a

  security_group_id = aws_security_group.production_build[0].id
  description       = "DNS to the VPC resolver, TCP fallback."
  cidr_ipv4         = local.production_vpc_resolver_cidr
  ip_protocol       = "tcp"
  from_port         = 53
  to_port           = 53
}

# ---------------------------------------------------------------------------
# Acquisition task security group -- the build's rules plus the provider allowlist
# ---------------------------------------------------------------------------

resource "aws_security_group" "production_acquisition" {
  count = local.production_count_a

  name        = "${var.name_prefix}-production-acquisition-task"
  description = "ADR-0036 acquisition task egress: S3 gateway, interface endpoints, VPC DNS, the provider address set. No inbound rule exists."
  vpc_id      = aws_vpc.research.id

  # THERE IS NO `ingress` BLOCK, AND NO 0.0.0.0/0 EGRESS RULE BELOW: the provider
  # rule is one entry per supplied CIDR, and the variable refuses 0.0.0.0/0.

  tags = {
    Name    = "${var.name_prefix}-production-acquisition-task"
    Purpose = "production-acquisition"
  }
}

resource "aws_vpc_security_group_egress_rule" "production_acquisition_s3" {
  count = local.production_count_a

  security_group_id = aws_security_group.production_acquisition[0].id
  description       = "HTTPS to S3 through the gateway endpoint's prefix list."
  prefix_list_id    = aws_vpc_endpoint.production_s3[0].prefix_list_id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_egress_rule" "production_acquisition_endpoints" {
  count = local.production_count_a

  security_group_id            = aws_security_group.production_acquisition[0].id
  description                  = "HTTPS to the interface endpoints."
  referenced_security_group_id = aws_security_group.production_endpoints[0].id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}

resource "aws_vpc_security_group_egress_rule" "production_acquisition_dns_udp" {
  count = local.production_count_a

  security_group_id = aws_security_group.production_acquisition[0].id
  description       = "DNS to the VPC resolver."
  cidr_ipv4         = local.production_vpc_resolver_cidr
  ip_protocol       = "udp"
  from_port         = 53
  to_port           = 53
}

resource "aws_vpc_security_group_egress_rule" "production_acquisition_dns_tcp" {
  count = local.production_count_a

  security_group_id = aws_security_group.production_acquisition[0].id
  description       = "DNS to the VPC resolver, TCP fallback."
  cidr_ipv4         = local.production_vpc_resolver_cidr
  ip_protocol       = "tcp"
  from_port         = 53
  to_port           = 53
}

# One rule per provider CIDR, from the apply-time allowlist. The mechanism ADR-0036
# s.2.8 names for the acquisition origin restriction.
resource "aws_vpc_security_group_egress_rule" "production_acquisition_provider" {
  for_each = local.production_stage_a ? toset(var.production_provider_origin_cidrs) : toset([])

  security_group_id = aws_security_group.production_acquisition[0].id
  description       = "HTTPS to one resolved provider origin address block."
  cidr_ipv4         = each.key
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}
