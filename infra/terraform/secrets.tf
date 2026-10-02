# Secrets live in Secrets Manager and are injected into containers as
# environment variables by ECS. They are never written into a task
# definition, an image, or this repository.
#
# Terraform generates two of them, which means their values are in the
# Terraform state. Treat the state as a secret (see versions.tf).

resource "random_bytes" "master_key" {
  length = 32
}

locals {
  secrets = {
    database_url = format(
      "postgresql+asyncpg://%s:%s@%s:%d/%s",
      aws_db_instance.main.username,
      random_password.database.result,
      aws_db_instance.main.address,
      aws_db_instance.main.port,
      aws_db_instance.main.db_name,
    )
    master_key           = random_bytes.master_key.base64
    google_client_secret = var.google_client_secret
  }
}

# for_each runs over the names only: a collection that contains sensitive
# values cannot be iterated, and the names are not secret.
resource "aws_secretsmanager_secret" "app" {
  for_each = toset(["database_url", "master_key", "google_client_secret"])

  name_prefix = "${var.name}/${each.key}-"
}

resource "aws_secretsmanager_secret_version" "app" {
  for_each = aws_secretsmanager_secret.app

  secret_id     = each.value.id
  secret_string = local.secrets[each.key]
}

resource "aws_secretsmanager_secret" "anthropic" {
  count = local.ai_enabled ? 1 : 0

  name_prefix = "${var.name}/anthropic_api_key-"
}

resource "aws_secretsmanager_secret_version" "anthropic" {
  count = local.ai_enabled ? 1 : 0

  secret_id     = aws_secretsmanager_secret.anthropic[0].id
  secret_string = var.anthropic_api_key
}
