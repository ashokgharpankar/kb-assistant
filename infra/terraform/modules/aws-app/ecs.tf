# ---------------------------------------------------------------------------
# ECS on Fargate (ADR 0014): one service, one task, two containers.
# web (nginx, :8080) proxies /api/ to the api container on localhost:8000, the same
# layout as Docker Compose and the Kubernetes pod network, without service discovery.
# The hardening from Phases 6a and 6b carries over: non-root users, read-only root
# filesystems with writable scratch volumes, health checks.
# ---------------------------------------------------------------------------

resource "aws_ecs_cluster" "main" {
  #checkov:skip=CKV_AWS_65:Container Insights costs per metric; the ALB and log metrics are enough in dev.
  name = var.name

  setting {
    name  = "containerInsights"
    value = "disabled"
  }
}

resource "aws_cloudwatch_log_group" "app" {
  #checkov:skip=CKV_AWS_158:Logs encrypted with the CloudWatch-managed key; a customer-managed key adds cost and nothing in dev.
  #checkov:skip=CKV_AWS_338:14-day retention is deliberate for dev (cost); production keeps a year.
  for_each          = toset(["api", "web"])
  name              = "/ecs/${var.name}/${each.key}"
  retention_in_days = var.log_retention_days
}

# --- IAM: two roles with different jobs -------------------------------------

data "aws_iam_policy_document" "ecs_tasks_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# The execution role is used by ECS itself: pull images, write logs, read the DB secret
# and inject it as environment variables. The application code never gets it.
resource "aws_iam_role" "execution" {
  name               = "${var.name}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "execution_secret" {
  statement {
    sid       = "ReadTheDatabaseSecretOnly"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_rds_cluster.main.master_user_secret[0].secret_arn]
  }
}

resource "aws_iam_role_policy" "execution_secret" {
  name   = "db-secret"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_secret.json
}

# The task role is what the application code runs as: the approved Bedrock models,
# nothing else. Same policy the developer role has used since Phase 0.
resource "aws_iam_role" "task" {
  name               = "${var.name}-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
}

resource "aws_iam_role_policy_attachment" "task_bedrock" {
  role       = aws_iam_role.task.name
  policy_arn = var.bedrock_policy_arn
}

# --- Task definition ------------------------------------------------------------

locals {
  cognito_authority = "https://cognito-idp.${var.region}.amazonaws.com/${var.cognito_user_pool_id}"
  db_secret_arn     = aws_rds_cluster.main.master_user_secret[0].secret_arn

  api_environment = merge(
    {
      KB_ENV                  = "dev"
      KB_LLM_PROVIDER         = "bedrock"
      KB_AWS_REGION           = var.region
      KB_AUTH_MODE            = "cognito"
      KB_COGNITO_USER_POOL_ID = var.cognito_user_pool_id
      KB_COGNITO_CLIENT_ID    = var.cognito_client_id
      # The API builds its database URL from these parts plus the injected secret.
      KB_DB_HOST = aws_rds_cluster.main.endpoint
      KB_DB_PORT = tostring(aws_rds_cluster.main.port)
      KB_DB_NAME = aws_rds_cluster.main.database_name
    },
    var.api_environment,
  )

  log_config = {
    for c in ["api", "web"] : c => {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.app[c].name
        awslogs-region        = var.region
        awslogs-stream-prefix = c
      }
    }
  }
}

resource "aws_ecs_task_definition" "app" {
  family                   = var.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64" # CI builds linux/amd64 images
  }

  # Writable scratch space on read-only root filesystems. Fargate creates these as
  # root-owned 0755 directories unless the image declares the same path with VOLUME;
  # then it copies that directory, owner and mode included (see the Dockerfiles).
  volume { name = "api-tmp" }
  volume { name = "web-tmp" }
  volume { name = "web-conf" }

  container_definitions = jsonencode([
    {
      name                   = "api"
      image                  = var.api_image
      essential              = true
      user                   = "10001"
      readonlyRootFilesystem = true
      portMappings           = [{ containerPort = 8000, protocol = "tcp" }]
      environment            = [for k, v in local.api_environment : { name = k, value = v }]
      # Injected by ECS from Secrets Manager at start-up: never in the task definition.
      secrets = [
        { name = "KB_DB_USERNAME", valueFrom = "${local.db_secret_arn}:username::" },
        { name = "KB_DB_PASSWORD", valueFrom = "${local.db_secret_arn}:password::" },
      ]
      mountPoints = [{ sourceVolume = "api-tmp", containerPath = "/tmp" }]
      healthCheck = {
        command     = ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60 # model clients and the embedder load at start-up
      }
      linuxParameters  = { capabilities = { drop = ["ALL"] } }
      logConfiguration = local.log_config["api"]
    },
    {
      name                   = "web"
      image                  = var.web_image
      essential              = true
      user                   = "101"
      readonlyRootFilesystem = true
      portMappings           = [{ containerPort = 8080, protocol = "tcp" }]
      environment = [
        { name = "API_UPSTREAM", value = "http://127.0.0.1:8000" },
        { name = "VITE_COGNITO_AUTHORITY", value = local.cognito_authority },
        { name = "VITE_COGNITO_CLIENT_ID", value = var.cognito_client_id },
        { name = "VITE_COGNITO_DOMAIN", value = var.cognito_domain },
      ]
      mountPoints = [
        { sourceVolume = "web-tmp", containerPath = "/tmp" },
        { sourceVolume = "web-conf", containerPath = "/etc/nginx/conf.d" },
      ]
      dependsOn = [{ containerName = "api", condition = "HEALTHY" }]
      healthCheck = {
        command     = ["CMD-SHELL", "wget -qO- http://127.0.0.1:8080/healthz || exit 1"]
        interval    = 30
        timeout     = 3
        retries     = 3
        startPeriod = 10
      }
      linuxParameters  = { capabilities = { drop = ["ALL"] } }
      logConfiguration = local.log_config["web"]
    },
  ])
}

resource "aws_ecs_service" "app" {
  #checkov:skip=CKV_AWS_333:Tasks get a public IP instead of a NAT Gateway (ADR 0015); the task SG accepts only the ALB.
  name                   = var.name
  cluster                = aws_ecs_cluster.main.id
  task_definition        = aws_ecs_task_definition.app.arn
  desired_count          = var.desired_count
  launch_type            = "FARGATE"
  platform_version       = "LATEST"
  enable_execute_command = false

  # The API can take ~60 s to become healthy (embedder load, Aurora resume).
  health_check_grace_period_seconds = 120

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.task.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.web.arn
    container_name   = "web"
    container_port   = 8080
  }

  # A deployment whose tasks never become healthy rolls back on its own.
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [aws_lb_listener_rule.from_cloudfront]
}
