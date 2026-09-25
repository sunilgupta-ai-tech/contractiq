# ContractIQ — Backend

FastAPI · async SQLAlchemy 2 · Alembic · Pydantic v2 · Qdrant · Redis.

```bash
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload
pytest -q                                              # unit
CONTRACTIQ_INTEGRATION=1 pytest tests/integration      # real Postgres/Redis/Qdrant
ruff check app tests
```

Layering: `api/v1` (thin handlers) → `services/` (business logic) → `db/repositories` (tenant-scoped data access) / `vectorstore` / `storage` / `llm`. Infrastructure clients live in `core/resources.py`, are created in the app lifespan, and are injected via `core/dependencies.py`.

See the root README and `docs/` for architecture, API, database and security notes.
