# ContractIQ — Worker

arq consumer on Redis queue `contractiq:documents`. Reuses the backend's domain package (`app.*`); the worker's own package is imported as `worker.*`.

* `tasks/document_processing.py` — runs the pipeline, committing status, progress and stage timings to PostgreSQL after every stage; on failure records `FAILED` and re-raises so arq retries (max 3).
* `services/pipeline.py` — ordered stages mapped 1:1 to `DocumentStatus`. Handlers are filled in by Phases 4–6.

Run: `make worker-dev` (native) or the `worker` compose service.
