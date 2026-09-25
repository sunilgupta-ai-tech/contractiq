# Troubleshooting

| Symptom | Check |
|---|---|
| `/ready` returns 503 | The `dependencies` array names the failing service. `docker compose ps` and `docker compose logs <service>`. |
| Worker shows `down` on System health | No arq heartbeat in Redis. `docker compose logs worker`. It is non-critical: queries still work. |
| Backend exits at startup with `JWT_SECRET_KEY must be set` | `APP_ENV` is not `development`; set a real secret. |
| Frontend shows "Cannot reach the ContractIQ API" | `NEXT_PUBLIC_API_BASE_URL` is baked in at build time — rebuild the frontend after changing it; check `CORS_ORIGINS`. |
| Migration fails with "type … already exists" | A previous partial run left enum types; `make migrate` after `alembic downgrade base`, or drop the types. |
| Ollama unreachable from containers | Use `OLLAMA_BASE_URL=http://host.docker.internal:11434` (Linux: add `extra_hosts: ["host.docker.internal:host-gateway"]`). |
