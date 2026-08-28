# ECS -- a cluster for ephemeral one-off tasks.
#
# STORAGE PERSISTS; COMPUTE IS EPHEMERAL (ADR-0007 §5). There is no always-on
# research server, no service, no desired count and no autoscaling group. A job
# starts, works, writes to S3 and exits.
#
# An empty ECS cluster costs nothing. Charges begin only when a Fargate task
# actually runs, billed per second with a one-minute minimum.
#
# NO TASK DEFINITION EXISTS AND NO TASK IS RUN.
#
# A task definition would have to name a container image, and no image has been
# built -- the registry in ecr.tf is empty. Committing a task definition
# referencing an image that does not exist would be a resource that cannot run,
# described as though it could. The task definition arrives with the authorized
# slice that also produces the image.
#
# AWS Batch and EC2 Spot are the documented scaling path for heavy backtests
# (ADR-0007 §5) and are deliberately NOT provisioned here. Adding them before
# there is a workload to measure would be provisioning against a guess.

resource "aws_ecs_cluster" "research" {
  name = "${var.name_prefix}-research"

  setting {
    # Container Insights is billed per metric and per log ingested. It is off
    # until there is a workload whose behaviour is worth that much per month;
    # CloudWatch Logs already captures what a one-off job needs to report.
    name  = "containerInsights"
    value = "disabled"
  }

  tags = {
    Name = "${var.name_prefix}-research"
  }
}

resource "aws_ecs_cluster_capacity_providers" "research" {
  cluster_name = aws_ecs_cluster.research.name

  # Both are declared so a future task can choose per run: FARGATE for work that
  # must not be interrupted, FARGATE_SPOT for cheap interruptible batch research.
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  # No default strategy. A run must state which it wants, so that "this job was
  # interruptible" is a recorded decision rather than an inherited default.
}
