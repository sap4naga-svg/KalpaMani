# Outputs.
#
# These are values produced AT APPLY TIME. Nothing here is committed, because
# nothing here has a value until an apply that has not been authorized.
#
# Some of them are identifiers -- the ECR repository URL embeds an account id --
# so an apply's output must not be pasted into a commit message, an issue, a
# public document or an AI chat session.

output "licensed_bucket_name" {
  description = "Licensed-data bucket. Bronze/silver/gold; deletion-friendly; no versioning."
  value       = aws_s3_bucket.licensed.id
}

output "control_bucket_name" {
  description = "Control bucket. Manifests, lineage, receipts, approved non-reconstructable outputs."
  value       = aws_s3_bucket.control.id
}

output "ecr_repository_url" {
  description = "Private research image registry. Contains an account id -- do not publish."
  value       = aws_ecr_repository.research.repository_url
}

output "ecs_cluster_name" {
  description = "Cluster for one-off research and ingestion tasks. No task definition exists yet."
  value       = aws_ecs_cluster.research.name
}

output "vpc_id" {
  description = "Research VPC."
  value       = aws_vpc.research.id
}

output "public_subnet_ids" {
  description = "Egress-capable subnets for ephemeral tasks."
  value       = aws_subnet.public[*].id
}

output "task_security_group_id" {
  description = "Task security group. Egress only; zero inbound rules."
  value       = aws_security_group.research_task.id
}

output "task_role_arn" {
  description = "Role assumed by research code. Contains an account id -- do not publish."
  value       = aws_iam_role.task.arn
}

output "task_execution_role_arn" {
  description = "Role assumed by the ECS agent. Contains an account id -- do not publish."
  value       = aws_iam_role.task_execution.arn
}

output "licensed_data_deletion_role_arn" {
  description = <<-EOT
    The ONLY identity that may destroy licensed data, used solely for an authorized
    vendor-termination deletion or rehearsal -- never for routine research.

    Nothing can assume it as committed: no deletion task exists and no identity is
    granted iam:PassRole for it. Contains an account id -- do not publish.
  EOT
  value       = aws_iam_role.licensed_data_deletion.arn
}

output "log_group_name" {
  description = "Task log group. Never a destination for payloads or credentials."
  value       = aws_cloudwatch_log_group.research.name
}

output "qualification_acquisition_policy_arn" {
  description = <<-EOT
    ADR-0018/0019 qualification acquisition permission set. Write-only on the
    licensed qualification prefixes, plus the one governed secret retrieval.

    ATTACHED TO NOTHING as committed: no role holds it, so it grants nothing. The
    trust principal is a separate architecture decision, and attaching this is a
    separate authorization. Contains an account id -- do not publish.
  EOT
  value       = aws_iam_policy.qualification_acquisition.arn
}

output "qualification_assessment_policy_arn" {
  description = <<-EOT
    ADR-0018 qualification assessment permission set. Exact evidence reads and one
    conditional private report; no credential, no provider, no listing, no delete.

    ATTACHED TO NOTHING as committed. Contains an account id -- do not publish.
  EOT
  value       = aws_iam_policy.qualification_assessment.arn
}
