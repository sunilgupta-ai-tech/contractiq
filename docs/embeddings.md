# Embeddings & Qdrant indexing (Phase 6)

Turns each **child** chunk into a dense vector (meaning) and a sparse vector (keywords) and stores it in Qdrant; stores **parent** chunks as vector-less points for small-to-big retrieval.

## Flow

```text
chunks.json (Phase 5)
   │
   ├─ embed  (status EMBEDDING)
   │    EmbeddingService: Redis cache (per tenant, by content hash)
   │                      → provider in batches of 100 → retry 429/5xx with backoff
   │    provider: Gemini (default) or Ollama
   │
   └─ index  (status INDEXING)
        check collection dimension
        build points: child = dense + sparse vectors, parent = no vectors
        upsert → prune this version's stale points (no search gap)
        newest version? → is_current=true, older versions → false
```

## Choosing the provider

**Gemini (default)** — hosted; sends chunk text to Google (check your API tier's data terms).

```env
EMBEDDING_PROVIDER=gemini
EMBEDDING_MODEL=gemini-embedding-001
EMBEDDING_DIMENSION=768
GEMINI_API_KEY=<your key>
```

**Ollama (optional, fully local)** — free, private; needs Ollama running with the model pulled (`ollama pull nomic-embed-text`).

```env
EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIMENSION=768
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

Both use task-aware embedding: Gemini via `taskType` (`RETRIEVAL_DOCUMENT` for chunks, `RETRIEVAL_QUERY` for questions), nomic models via `search_document:` / `search_query:` prefixes.

Outside `development`, the app refuses to start if a Gemini provider is selected without `GEMINI_API_KEY`.

## Point payload (per chunk)

`tenant_id`, `document_id`, `version_id`, `version_label`, `chunk_id`, `parent_id`, `level` (child/parent), `chunk_type`, `document_title`, `contract_type`, `is_current`, `section`, `section_title`, `clause`, `clause_title`, `clauses`, `heading_path`, `page`, `page_end`, `regions`, `text`, `token_count`, `embedding_model` (`provider:model:dimension`), `chunker_version`.

Indexed for filtering: `tenant_id` (tenant-partitioned), `document_id`, `version_id`, `contract_type`, `section`, `clause`, `chunk_type`, `page`, `level`, `is_current`, `embedding_model`. Missing indexes are added to an existing collection on startup.

## Guarantees

| Property | How |
|---|---|
| Tenant isolation | every point has `tenant_id`; all queries/deletes use `tenant_filter()`; parent lookup by id re-checks the tenant |
| Idempotent re-processing | deterministic chunk ids → upsert overwrites; stale ids of the version are pruned after the upsert |
| No search gap while re-indexing | upsert first, prune second |
| Old versions kept for comparison | `is_current=false`, still indexed; default search uses `is_current=true` (Phase 7) |
| Re-processing an old version never demotes a newer one | only the newest `version_number` becomes current |
| Never compare vectors of different models | `embedding_model` on every point; search filters on the current model (Phase 7) |
| Clear error on dimension mismatch | `check_dimension()` before indexing |

## Cost controls

* Cache: identical text (same tenant, model, dimension, task) is embedded once; hits/misses/API calls/retries are stored per version in `extraction_metadata.embedding`. New contract versions mostly reuse v1's clauses.
* Batching: 100 texts per Gemini call (`EMBEDDING_BATCH_SIZE`).
* Retries: `EMBEDDING_MAX_RETRIES` (5) with exponential backoff + jitter, only for 408/429/5xx/network errors. Bad keys and bad requests fail at once.

## Changing the embedding model

1. **Same dimension** (e.g. Gemini → Ollama, both 768): change `EMBEDDING_PROVIDER`/`EMBEDDING_MODEL`, restart, then enqueue `reembed_tenant` for each tenant. Until a document is re-embedded it is absent from search (filtered by `embedding_model`), never mis-matched.
2. **Different dimension**: also set a new `QDRANT_COLLECTION` and `EMBEDDING_DIMENSION` (the new collection is created on startup), run `reembed_tenant` for each tenant, then delete the old collection.

`reembed_tenant` re-uses each version's `chunks.json` — no parsing, OCR or chunking is repeated:

```python
await queue.enqueue_job("reembed_tenant", "<tenant uuid>")
```

## Settings

`EMBEDDING_PROVIDER` (gemini), `EMBEDDING_MODEL` (gemini-embedding-001), `EMBEDDING_DIMENSION` (768), `EMBEDDING_BATCH_SIZE` (100), `EMBEDDING_MAX_RETRIES` (5), `EMBEDDING_TIMEOUT_S` (60), `EMBEDDING_CACHE_TTL_S` (30 days; 0 disables), `QDRANT_COLLECTION` (contract_chunks).
