# Networking -- outbound only, and nothing that answers.
#
# The security requirement is stated as an absence: there is no service, no
# listener, no port, no load balancer and no inbound rule. A research task dials
# out to a provider API, SEC EDGAR, ECR and CloudWatch, and nothing ever dials in.
#
# WHY PUBLIC SUBNETS RATHER THAN PRIVATE SUBNETS BEHIND A NAT GATEWAY
#
# The textbook design puts tasks in private subnets and routes egress through a
# NAT Gateway. A NAT Gateway bills hourly whether or not anything uses it -- on
# the order of USD 30-35/month at current public pricing, before per-GB processing
# -- for an account that is idle almost all of the time. That is recurring money
# spent to make an already-unreachable task unaddressable.
#
# A public IP makes a task ADDRESSABLE, not REACHABLE. Reachability needs an
# inbound security-group rule, and there are none below. Security groups deny
# inbound by default and are STATEFUL, so replies to the task's own outbound
# connections return without any inbound rule existing. Nothing is listening.
#
# THIS ARGUMENT IS CONDITIONAL ON THERE NEVER BEING A LISTENER. The moment any
# component must accept a connection, this design is wrong and must be replaced by
# private subnets with a NAT Gateway or -- better for an S3-dominated workload --
# VPC endpoints: a Gateway endpoint for S3 (no hourly charge) plus Interface
# endpoints for ECR and CloudWatch Logs (hourly, per AZ). ADR-0007 §6.
#
# S3 Block Public Access is independent of all of this and is mandatory regardless.

resource "aws_vpc" "research" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "${var.name_prefix}-vpc"
  }
}

resource "aws_internet_gateway" "research" {
  vpc_id = aws_vpc.research.id

  # An internet gateway carries no hourly charge. It is the egress path itself
  # that is free here; only a NAT Gateway would not be.
  tags = {
    Name = "${var.name_prefix}-igw"
  }
}

resource "aws_subnet" "public" {
  count = length(local.availability_zones)

  vpc_id            = aws_vpc.research.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index)
  availability_zone = local.availability_zones[count.index]

  # A public IP is assigned per-task at RunTask time, not implicitly to everything
  # launched here. A task that needs no egress runs without one.
  map_public_ip_on_launch = false

  tags = {
    Name = "${var.name_prefix}-public-${local.availability_zones[count.index]}"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.research.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.research.id
  }

  tags = {
    Name = "${var.name_prefix}-public"
  }
}

resource "aws_route_table_association" "public" {
  count = length(aws_subnet.public)

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# ---------------------------------------------------------------------------
# Security group -- zero inbound rules, by construction
# ---------------------------------------------------------------------------

resource "aws_security_group" "research_task" {
  name        = "${var.name_prefix}-task"
  description = "Research task egress. No inbound rules exist, and none may be added."
  vpc_id      = aws_vpc.research.id

  # THERE IS NO `ingress` BLOCK IN THIS RESOURCE, AND THAT IS THE POINT.
  #
  # Adding one is not a configuration tweak: the entire justification for running
  # tasks in a public subnet rather than behind a NAT Gateway is that this group
  # admits nothing. Anyone adding an ingress rule must revisit ADR-0007 §6 first.

  tags = {
    Name = "${var.name_prefix}-task"
  }
}

resource "aws_vpc_security_group_egress_rule" "https" {
  security_group_id = aws_security_group.research_task.id
  description       = "Outbound HTTPS: provider API, SEC EDGAR, ECR, CloudWatch, S3."

  cidr_ipv4   = "0.0.0.0/0"
  ip_protocol = "tcp"
  from_port   = 443
  to_port     = 443
}

# DNS is scoped to the VPC rather than the internet: the Amazon-provided resolver
# lives inside the VPC CIDR, and security-group rules apply to that traffic too.
# A 443-only egress group resolves no names and fails in a way that looks like a
# provider outage.
resource "aws_vpc_security_group_egress_rule" "dns_udp" {
  security_group_id = aws_security_group.research_task.id
  description       = "DNS to the VPC resolver."

  cidr_ipv4   = var.vpc_cidr
  ip_protocol = "udp"
  from_port   = 53
  to_port     = 53
}

resource "aws_vpc_security_group_egress_rule" "dns_tcp" {
  security_group_id = aws_security_group.research_task.id
  description       = "DNS to the VPC resolver, TCP fallback for large responses."

  cidr_ipv4   = var.vpc_cidr
  ip_protocol = "tcp"
  from_port   = 53
  to_port     = 53
}

# No plaintext HTTP egress rule. Every endpoint this system talks to serves HTTPS,
# and an API key in a query string over port 80 would be a credential sent in
# clear text (ADR-0007 §8).
