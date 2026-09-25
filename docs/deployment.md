# Deployment: local → production

## Local
`make up` builds and starts all six services plus a one-shot `migrate` job. Containers reach each other by service name (`postgres`, `redis`, `qdrant`).

## AWS reference topology

```text
Route 53 → ALB (HTTPS, ACM cert)
            ├─ /           → ECS service: frontend (Next.js standalone)
            └─ /api/*      → ECS service: backend (uvicorn, 2 workers/task)
ECS service: worker (arq)  — autoscale on queue depth
RDS PostgreSQL (Multi-AZ, private subnets)
ElastiCache Redis (TLS, private subnets)
Qdrant Cloud (VPC peering / PrivateLink) or Qdrant on ECS/EKS with EBS
S3 bucket (SSE, block public access, lifecycle rules per tenants/ prefix)
Secrets Manager → task definitions; CloudWatch Logs + alarms
```

Environment differences are configuration only:

```env
APP_ENV=production
LOG_JSON=true
DATABASE_URL=postgresql+asyncpg://…@<rds-endpoint>:5432/contractiq
REDIS_URL=rediss://<elasticache-endpoint>:6379/0
QDRANT_URL=https://<cluster>.cloud.qdrant.io:6333
QDRANT_API_KEY=<secret>
STORAGE_BACKEND=s3
AWS_S3_BUCKET=contractiq-prod-documents
CORS_ORIGINS=https://app.example.com
JWT_SECRET_KEY=<secret>
```

Release order: build images → push to ECR → run `alembic upgrade head` as a one-off task → roll backend and worker → roll frontend. The ALB health check targets `/api/v1/ready`; ECS container health checks target `/api/v1/health`.

CI (`.github/workflows/ci.yml`) runs lint, unit tests, integration tests against service containers, and Docker builds on every push.
