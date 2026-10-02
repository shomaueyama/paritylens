resource "aws_ecs_cluster" "main" {
  name = var.name

  setting {
    name  = "containerInsights"
    value = "disabled" # extra cost; turn on when there is something to watch
  }
}

# Service Connect gives each service a name inside the VPC: the worker
# reaches the demo API at http://legacy-shop-api:8000, the web app reaches
# the API at http://api:8000.
resource "aws_service_discovery_http_namespace" "main" {
  name = var.name
}

resource "aws_cloudwatch_log_group" "app" {
  for_each = toset(["api", "worker", "web", "demo"])

  name              = "/${var.name}/${each.key}"
  retention_in_days = 30
}

locals {
  registry = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.region}.amazonaws.com"

  image = {
    for name in local.images : name => "${aws_ecr_repository.app[name].repository_url}:${var.image_tag}"
  }

  # Settings shared by the API and the worker. Plain values here; anything
  # secret is in `backend_secrets` and comes from Secrets Manager.
  backend_environment = [
    { name = "PARITYLENS_ENVIRONMENT", value = "production" },
    { name = "PARITYLENS_PUBLIC_BASE_URL", value = local.public_base_url },
    { name = "PARITYLENS_AUTH_MODE", value = "google" },
    { name = "PARITYLENS_GOOGLE_CLIENT_ID", value = var.google_client_id },
    # The public deployment calls the demo APIs and nothing else.
    { name = "PARITYLENS_EGRESS_MODE", value = "allowlist" },
    { name = "PARITYLENS_EGRESS_ALLOW_HOSTS", value = local.egress_allow_hosts },
    { name = "PARITYLENS_LLM_PROVIDER", value = local.ai_enabled ? "anthropic" : "none" },
  ]

  backend_secrets = [
    { name = "PARITYLENS_DATABASE_URL", valueFrom = aws_secretsmanager_secret.app["database_url"].arn },
    { name = "PARITYLENS_MASTER_KEY", valueFrom = aws_secretsmanager_secret.app["master_key"].arn },
    { name = "PARITYLENS_GOOGLE_CLIENT_SECRET", valueFrom = aws_secretsmanager_secret.app["google_client_secret"].arn },
  ]

  # Only the worker talks to the model provider, so only it gets the key.
  worker_secrets = concat(local.backend_secrets, [
    for secret in aws_secretsmanager_secret.anthropic : { name = "ANTHROPIC_API_KEY", valueFrom = secret.arn }
  ])
}

# --- task definitions ------------------------------------------------------

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task["api"].arn

  container_definitions = jsonencode([{
    name      = "api"
    image     = local.image["api"]
    essential = true
    # Apply migrations, then serve. With one task this is safe; with more
    # than one, run migrations as a separate one-off task before rolling out.
    command                = ["sh", "-c", "python -m paritylens_api.migrate && exec uvicorn paritylens_api.main:app --host 0.0.0.0 --port 8000"]
    portMappings           = [{ name = "api", containerPort = 8000, protocol = "tcp" }]
    environment            = local.backend_environment
    secrets                = local.backend_secrets
    readonlyRootFilesystem = true
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.app["api"].name
        awslogs-region        = var.region
        awslogs-stream-prefix = "api"
      }
    }
  }])
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.name}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task["worker"].arn

  container_definitions = jsonencode([{
    name                   = "worker"
    image                  = local.image["api"] # same image as the API, different command
    essential              = true
    command                = ["python", "-m", "paritylens_api.worker"]
    environment            = local.backend_environment
    secrets                = local.worker_secrets
    readonlyRootFilesystem = true
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.app["worker"].name
        awslogs-region        = var.region
        awslogs-stream-prefix = "worker"
      }
    }
  }])
}

resource "aws_ecs_task_definition" "web" {
  family                   = "${var.name}-web"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task["web"].arn

  container_definitions = jsonencode([{
    name         = "web"
    image        = local.image["web"]
    essential    = true
    portMappings = [{ name = "web", containerPort = 3000, protocol = "tcp" }]
    environment  = [{ name = "API_INTERNAL_URL", value = "http://api:8000" }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.app["web"].name
        awslogs-region        = var.region
        awslogs-stream-prefix = "web"
      }
    }
  }])
}

resource "aws_ecs_task_definition" "demo" {
  for_each = local.demo_services

  family                   = "${var.name}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task["demo"].arn

  container_definitions = jsonencode([{
    name                   = each.key
    image                  = local.image[each.key]
    essential              = true
    portMappings           = [{ name = each.key, containerPort = 8000, protocol = "tcp" }]
    readonlyRootFilesystem = true
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.app["demo"].name
        awslogs-region        = var.region
        awslogs-stream-prefix = each.key
      }
    }
  }])
}

# --- services --------------------------------------------------------------

resource "aws_ecs_service" "api" {
  name            = "api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  # New versions are rolled out by the deploy workflow, which registers a
  # new task definition revision. Terraform owns the service's shape, not
  # which revision it currently runs.
  lifecycle {
    ignore_changes = [task_definition]
  }

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.api.id]
    assign_public_ip = true # no NAT gateway; see network.tf
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  service_connect_configuration {
    enabled   = true
    namespace = aws_service_discovery_http_namespace.main.arn
    service {
      port_name      = "api"
      discovery_name = "api"
      client_alias {
        dns_name = "api"
        port     = 8000
      }
    }
  }

  # If a new version cannot become healthy, go back to the previous one.
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [aws_lb_listener.https]
}

resource "aws_ecs_service" "worker" {
  name            = "worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  # New versions are rolled out by the deploy workflow, which registers a
  # new task definition revision. Terraform owns the service's shape, not
  # which revision it currently runs.
  lifecycle {
    ignore_changes = [task_definition]
  }

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.worker.id]
    assign_public_ip = true
  }

  # A client of the namespace: it can resolve the demo APIs by name.
  service_connect_configuration {
    enabled   = true
    namespace = aws_service_discovery_http_namespace.main.arn
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # The API task applies the migrations; start after it.
  depends_on = [aws_ecs_service.api, aws_ecs_service.demo]
}

resource "aws_ecs_service" "web" {
  name            = "web"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.web.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  # New versions are rolled out by the deploy workflow, which registers a
  # new task definition revision. Terraform owns the service's shape, not
  # which revision it currently runs.
  lifecycle {
    ignore_changes = [task_definition]
  }

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.web.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.web.arn
    container_name   = "web"
    container_port   = 3000
  }

  service_connect_configuration {
    enabled   = true
    namespace = aws_service_discovery_http_namespace.main.arn
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [aws_lb_listener.https, aws_ecs_service.api]
}

resource "aws_ecs_service" "demo" {
  for_each = local.demo_services

  name            = each.key
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.demo[each.key].arn
  desired_count   = 1
  launch_type     = "FARGATE"

  # New versions are rolled out by the deploy workflow, which registers a
  # new task definition revision. Terraform owns the service's shape, not
  # which revision it currently runs.
  lifecycle {
    ignore_changes = [task_definition]
  }

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.demo.id]
    assign_public_ip = true
  }

  service_connect_configuration {
    enabled   = true
    namespace = aws_service_discovery_http_namespace.main.arn
    service {
      port_name      = each.key
      discovery_name = each.key
      client_alias {
        dns_name = each.key
        port     = 8000
      }
    }
  }
}
