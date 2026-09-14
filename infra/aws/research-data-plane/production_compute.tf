# ADR-0036 production data-plane principals -- THE TASK DEFINITIONS.
#
# One family per actor, Fargate, image pinned BY DIGEST from the one research
# repository, the actor's task role, the foundation's execution role, `awslogs` to
# the research log group under a per-actor stream prefix (ADR-0036 s.2.9).
#
# WHAT IS DELIBERATELY ABSENT, AND WHY EACH ABSENCE IS A CONTROL
#
#   no `secrets`         bindings, inputs and releases are read by the TASK ROLE
#                        inside the container (production_policies.tf), never
#                        injected by the agent -- so the execution role stays
#                        data-blind and holds no ssm, secretsmanager or kms action.
#   no `environment`     no private value in an infrastructure document; the runner
#                        reads no environment variable but the metadata URI.
#   no `portMappings`    nothing listens (ADR-0007).
#   no `mountPoints`,    nothing persists past the task; the runner deletes its
#   no `volumes`         working directory before exit regardless.
#   `command` fixed      the runner's entrypoint, so a command override runs the same
#                        entrypoint or exits non-zero.
#   `readonlyRootFilesystem`  the image is not a scratch disk; the runner's working
#                        directory is a tmpfs mount declared below.
#
# The platform version is pinned at RunTask by the launch tool, not here: a task
# definition carries no platform version. `ecs.tf` records that the foundation
# declared no task definition because no image existed; these two are gated on the
# stage and on `production_image_digests`, so they still declare nothing until an
# image gate has built something to name.

locals {
  production_image_repository = aws_ecr_repository.research.repository_url

  production_acquire_family = "kalpamani-production-acquire"
  production_build_family   = "kalpamani-research-build"
  # Proposed ADR-0045 (not accepted): the verification families. The same actor, the
  # same task role, the same execution role, the same placement the launch tool
  # sends, the same read-only root and /work tmpfs -- a different image whose entry
  # composes the accepted bootstrap and stops at the release barrier (VERIFIED_BOOTSTRAP,
  # exit 18), constructing no secrets client, no transport and no S3 client.
  production_acquire_verify_family = "kalpamani-production-acquire-verify"
  production_build_verify_family   = "kalpamani-research-build-verify"

  # Fargate task size. 1 vCPU / 2 GiB covers 48 sequential provider requests and
  # a bounded build; raising it is a configuration change, not an ADR change.
  production_task_cpu    = "1024"
  production_task_memory = "2048"

  production_acquire_container = {
    name      = "acquire"
    image     = "${local.production_image_repository}@${lookup(var.production_image_digests, "acquisition", "sha256:unset")}"
    essential = true
    command   = ["kalpamani-production-acquire"]
    cpu       = 1024
    memory    = 2048
    user      = "10001:10001"
    linuxParameters = {
      initProcessEnabled = true
      tmpfs = [{
        containerPath = "/work"
        size          = 512
        mountOptions  = ["rw", "noexec", "nosuid"]
      }]
    }
    readonlyRootFilesystem = true
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.research.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "production-acquire"
      }
    }
  }

  production_build_container = {
    name      = "build"
    image     = "${local.production_image_repository}@${lookup(var.production_image_digests, "build", "sha256:unset")}"
    essential = true
    command   = ["kalpamani-research-build"]
    cpu       = 1024
    memory    = 2048
    user      = "10001:10001"
    linuxParameters = {
      initProcessEnabled = true
      tmpfs = [{
        containerPath = "/work"
        size          = 1024
        mountOptions  = ["rw", "noexec", "nosuid"]
      }]
    }
    readonlyRootFilesystem = true
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.research.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "production-build"
      }
    }
  }
}

# The verification containers (proposed ADR-0045): the production container's shape
# with a different name, image and command; declared only with their own digest below.
locals {
  production_acquire_verify_container = {
    name      = "acquire-verify"
    image     = "${local.production_image_repository}@${lookup(var.production_image_digests, "acquisition_verify", "sha256:unset")}"
    essential = true
    command   = ["kalpamani-production-acquire-verify"]
    cpu       = 1024
    memory    = 2048
    user      = "10001:10001"
    linuxParameters = {
      initProcessEnabled = true
      tmpfs = [{
        containerPath = "/work"
        size          = 512
        mountOptions  = ["rw", "noexec", "nosuid"]
      }]
    }
    readonlyRootFilesystem = true
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.research.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "production-acquire-verify"
      }
    }
  }

  production_build_verify_container = {
    name      = "build-verify"
    image     = "${local.production_image_repository}@${lookup(var.production_image_digests, "build_verify", "sha256:unset")}"
    essential = true
    command   = ["kalpamani-research-build-verify"]
    cpu       = 1024
    memory    = 2048
    user      = "10001:10001"
    linuxParameters = {
      initProcessEnabled = true
      tmpfs = [{
        containerPath = "/work"
        size          = 1024
        mountOptions  = ["rw", "noexec", "nosuid"]
      }]
    }
    readonlyRootFilesystem = true
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.research.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "production-build-verify"
      }
    }
  }
}

resource "aws_ecs_task_definition" "production_acquire" {
  count = local.production_count_a

  family                   = local.production_acquire_family
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = local.production_task_cpu
  memory                   = local.production_task_memory
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.production_acquire_task[0].arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([local.production_acquire_container])

  tags = {
    Purpose = "production-acquisition"
  }
}

resource "aws_ecs_task_definition" "production_build" {
  count = local.production_count_a

  family                   = local.production_build_family
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = local.production_task_cpu
  memory                   = local.production_task_memory
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.production_build_task[0].arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([local.production_build_container])

  tags = {
    Purpose = "production-build"
  }
}

# ---------------------------------------------------------------------------
# Verification families (proposed ADR-0045; declared only with their own digest)
# ---------------------------------------------------------------------------

resource "aws_ecs_task_definition" "production_acquire_verify" {
  count = local.production_acquire_verify_count

  family                   = local.production_acquire_verify_family
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = local.production_task_cpu
  memory                   = local.production_task_memory
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.production_acquire_task[0].arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([local.production_acquire_verify_container])

  tags = {
    Purpose = "production-acquisition-verification"
  }
}

resource "aws_ecs_task_definition" "production_build_verify" {
  count = local.production_build_verify_count

  family                   = local.production_build_verify_family
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = local.production_task_cpu
  memory                   = local.production_task_memory
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.production_build_task[0].arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([local.production_build_verify_container])

  tags = {
    Purpose = "production-build-verification"
  }
}
