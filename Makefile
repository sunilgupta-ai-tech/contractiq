.DEFAULT_GOAL := help
SHELL := /bin/bash

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

env: ## Create .env from .env.example if missing
	@test -f .env || cp .env.example .env && echo ".env ready"

up: env ## Start the full stack (frontend, backend, worker, postgres, redis, qdrant)
	docker compose up --build -d

down: ## Stop the stack
	docker compose down

logs: ## Tail logs for all services
	docker compose logs -f --tail=100

ps: ## Show service status
	docker compose ps

infra: env ## Start only postgres, redis and qdrant (for running apps natively)
	docker compose up -d postgres redis qdrant

migrate: ## Apply database migrations
	docker compose run --rm migrate

migration: ## Create a new migration: make migration m="add foo"
	cd backend && alembic revision --autogenerate -m "$(m)"

backend-dev: ## Run the API natively against `make infra`
	cd backend && DATABASE_URL=postgresql+asyncpg://contractiq:contractiq_dev_password@localhost:5432/contractiq \
	  REDIS_URL=redis://localhost:6379/0 QDRANT_URL=http://localhost:6333 \
	  uvicorn app.main:app --reload --port 8000

worker-dev: ## Run the worker natively against `make infra`
	mkdir -p workers/.run && ln -sfn ../app workers/.run/worker
	cd workers && PYTHONPATH=../backend:.run \
	  DATABASE_URL=postgresql+asyncpg://contractiq:contractiq_dev_password@localhost:5432/contractiq \
	  REDIS_URL=redis://localhost:6379/0 QDRANT_URL=http://localhost:6333 \
	  arq worker.main.WorkerSettings

frontend-dev: ## Run the Next.js dev server
	cd frontend && npm run dev

test: ## Run backend tests
	cd backend && pytest -q

platform-admin: ## Create the first platform (super) admin: make platform-admin email=you@x.com name="You"
	docker compose exec -it backend python -m app.platform_admin create --email "$(email)" --name "$(name)"

eval: ## Evaluate the RAG pipeline on the golden dataset (uses the configured models)
	docker compose exec backend python -m app.evaluation run --out /tmp/eval-reports

eval-baseline: ## Store this run as the regression baseline (backend/eval/baseline)
	docker compose exec backend python -m app.evaluation run --out /tmp/eval-reports
	docker compose cp backend:/tmp/eval-reports/report.json backend/eval/baseline/report.json

ops-status: ## Jobs, queue, worker, vectors and snapshots at a glance
	docker compose exec backend python -m app.ops status

recover-jobs: ## Requeue jobs a crash or Redis loss interrupted (the worker also does this every 5 min)
	docker compose exec backend python -m app.ops recover

reindex: ## Rebuild all vectors from stored chunks (after losing Qdrant)
	docker compose exec backend python -m app.ops reindex --all

backup-db: ## Dump PostgreSQL to backups/postgres/ (keeps 14 days)
	scripts/backup-postgres.sh

restore-db: ## Restore a dump (stop backend/worker first): make restore-db file=backups/postgres/x.dump
	scripts/restore-postgres.sh "$(file)" --yes

qdrant-snapshot: ## Snapshot the vector collection into storage (backups/qdrant/)
	docker compose exec backend python -m app.ops snapshot

secret-scan: ## Scan the git history for committed secrets (gitleaks, as in CI)
	docker run --rm -v "$$PWD":/repo zricethezav/gitleaks:v8.21.2 git /repo --redact --no-banner --exit-code 1

lint: ## Lint backend and frontend
	cd backend && ruff check app tests
	cd frontend && npm run lint

.PHONY: help env up down logs ps infra migrate migration backend-dev worker-dev frontend-dev test platform-admin eval eval-baseline ops-status recover-jobs reindex backup-db restore-db qdrant-snapshot secret-scan lint
