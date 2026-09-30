# Secrets are injected into ECS tasks as environment variables by the ECS
# agent (never baked into images or task-definition plain text).
#
# Generated here: DATABASE_URL, REDIS_URL, JWT_SECRET_KEY, METRICS_TOKEN.
# Provided by an operator after the first apply (values are NOT in code or
# state):
#   aws secretsmanager put-secret-value --secret-id <arn> --secret-string '...'
# for GEMINI_API_KEY and QDRANT_API_KEY (ARNs in the outputs). Tasks fail to
# start until those two have a value — by design.

resource "random_password" "jwt" {
  length  = 64
  special = false
}

resource "random_password" "metrics" {
  length  = 40
  special = false
}

locals {
  generated_secrets = {
    DATABASE_URL = "postgresql+asyncpg://contractiq:${random_password.db.result}@${aws_db_instance.main.address}:5432/contractiq?ssl=require"
    REDIS_URL    = "rediss://:${random_password.redis.result}@${aws_elasticache_replication_group.main.primary_endpoint_address}:6379/0"
    JWT_SECRET_KEY = random_password.jwt.result
    METRICS_TOKEN  = random_password.metrics.result
  }
  operator_secrets = ["GEMINI_API_KEY", "QDRANT_API_KEY"]
}

resource "aws_secretsmanager_secret" "generated" {
  for_each = local.generated_secrets
  name     = "${local.name}/${each.key}"
}

resource "aws_secretsmanager_secret_version" "generated" {
  for_each      = local.generated_secrets
  secret_id     = aws_secretsmanager_secret.generated[each.key].id
  secret_string = each.value
}

resource "aws_secretsmanager_secret" "operator" {
  for_each = toset(local.operator_secrets)
  name     = "${local.name}/${each.key}"
}

locals {
  secret_arns = merge(
    { for k, s in aws_secretsmanager_secret.generated : k => s.arn },
    { for k, s in aws_secretsmanager_secret.operator : k => s.arn },
  )
}
