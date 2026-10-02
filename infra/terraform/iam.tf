# Two kinds of role per task:
#
#   execution role : used by ECS itself to start the container (pull the
#                    image, fetch its secrets, create its log stream)
#   task role      : what the code inside the container may do in AWS
#
# The task roles below have no policies at all. Nothing in the application
# calls an AWS API, so if the worker were tricked into reaching the
# credentials endpoint, the credentials it found would open nothing.

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name_prefix        = "${var.name}-exec-"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "read_secrets" {
  statement {
    actions = ["secretsmanager:GetSecretValue"]
    resources = concat(
      [for secret in aws_secretsmanager_secret.app : secret.arn],
      aws_secretsmanager_secret.anthropic[*].arn,
    )
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  name_prefix = "read-secrets-"
  role        = aws_iam_role.execution.id
  policy      = data.aws_iam_policy_document.read_secrets.json
}

resource "aws_iam_role" "task" {
  for_each = toset(["api", "worker", "web", "demo"])

  name_prefix        = "${var.name}-${each.key}-"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

# --- deployment from GitHub Actions ----------------------------------------
#
# GitHub proves which repository and branch a workflow runs for with a
# short-lived signed token (OIDC); AWS exchanges it for temporary
# credentials. No long-lived access key is stored in GitHub.

data "aws_caller_identity" "current" {}

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "github_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    # Only workflows on the main branch of this one repository.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name               = "${var.name}-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_assume.json
}

data "aws_iam_policy_document" "deploy" {
  statement {
    sid       = "LogInToTheRegistry"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # this action does not support resource-level permissions
  }

  statement {
    sid = "PushImages"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:CompleteLayerUpload",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [for repository in aws_ecr_repository.app : repository.arn]
  }

  statement {
    sid       = "RegisterTaskDefinitions"
    actions   = ["ecs:RegisterTaskDefinition", "ecs:DescribeTaskDefinition"]
    resources = ["*"] # these actions do not support resource-level permissions
  }

  statement {
    sid       = "RollOutServices"
    actions   = ["ecs:UpdateService", "ecs:DescribeServices"]
    resources = ["arn:aws:ecs:${var.region}:${data.aws_caller_identity.current.account_id}:service/${aws_ecs_cluster.main.name}/*"]
  }

  statement {
    sid       = "HandRolesToNewTasks"
    actions   = ["iam:PassRole"]
    resources = concat([aws_iam_role.execution.arn], [for role in aws_iam_role.task : role.arn])
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "deploy" {
  name_prefix = "deploy-"
  role        = aws_iam_role.deploy.id
  policy      = data.aws_iam_policy_document.deploy.json
}
