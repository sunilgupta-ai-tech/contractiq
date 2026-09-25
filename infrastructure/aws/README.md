# AWS

Target topology and environment mapping: see `docs/deployment.md`.

Phase 14 adds IaC here (Terraform or CDK): VPC with private subnets, ECS cluster + three services (frontend, backend, worker), ALB + ACM, RDS PostgreSQL, ElastiCache Redis, S3 bucket with SSE and lifecycle rules, Secrets Manager entries, ECR repositories, CloudWatch log groups and alarms (5xx rate, `/ready` failures, queue depth, p95 latency).
