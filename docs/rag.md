# Contract Q&A — RAG (Phase 7)

`POST /api/v1/query` answers a question from the organization's contracts, citing document, version, page, section and clause for every statement.

## Flow

```text
POST /query  (role with query:run)
  │  validate: document_ids / version_ids exist in the caller's tenant (else 404)
  │  conversation: continue the caller's own, or start a new one
  │
  ├─ 1 retrieve   question → dense (Gemini, RETRIEVAL_QUERY) + keyword vector
  │               Qdrant: prefetch dense top-40 + sparse top-40 → RRF → top 20
  │               filter: tenant · level=child · embedding_model · is_current* · documents
  ├─ 2 rerank     clause references ("clause 8.3"), heading and text term overlap → top 6
  ├─ 3 context    hits → their parent sections (small-to-big), one block per section,
  │               within CONTEXT_MAX_TOKENS; blocks numbered [1]..[n]
  ├─ 4 generate   system rules + history + evidence in nonce-tagged <untrusted_document_*>
  │               blocks; temperature 0; one retry on 429/5xx
  └─ 5 cite       invented [n] removed, renumbered 1..k, resolved to page/clause/quote
  │
  └─ persist question + answer (citations, model, tokens, latency, request id)
```

\* `is_current` is dropped when `version_ids` are given, so a question can target an older version.

## Code map

| Module | Responsibility |
|---|---|
| `app/api/v1/query.py` | route (permission first) |
| `app/services/query_service.py` | scope validation, conversation, error mapping, persistence |
| `app/rag/pipelines/qa.py` | the five steps, timings, not-found / blocked handling |
| `app/services/retrieval_service.py` | production `Retriever`: embeddings + hybrid search + parents |
| `app/rag/hybrid_search.py` | `retrieval_filter()`, one-call RRF hybrid query |
| `app/rag/reranker.py` | `Reranker` protocol, `HeuristicReranker`, `NoopReranker` |
| `app/rag/context.py` | small-to-big evidence blocks within a token budget |
| `app/rag/prompts/system.py` | versioned prompt (`PROMPT_VERSION`), message building |
| `app/services/citation_service.py` | marker verification, renumbering, `cited_fraction` |

## Response

```json
{
  "id": "…assistant message id…",
  "conversation_id": "…",
  "question": "What is the notice period?",
  "answer": "Either party may terminate on 60 days' written notice [1].",
  "citations": [{
    "index": 1, "document_id": "…", "document_title": "Acme MSA",
    "version_id": "…", "version_label": "v2", "page": 12, "page_end": 12,
    "section": "8", "section_title": "Termination", "clause": "8.3", "clauses": ["8.3"],
    "quote": "…", "score": 1.9, "regions": [{"page": 12, "bbox": [72, 300, 520, 340]}]
  }],
  "insufficient_evidence": false,
  "cited_fraction": 1.0,
  "steps": [{"key": "retrieve", "label": "Hybrid search", "detail": "20 candidates", "duration_ms": 41.2, "status": "done"}],
  "model": "gemini-2.5-flash",
  "prompt_version": "qa-v2",
  "latency_ms": 1830,
  "usage": {"prompt_tokens": 2400, "completion_tokens": 80}
}
```

## Behaviour to know

| Situation | Result |
|---|---|
| Nothing retrieved | "couldn't find this" answer, `insufficient_evidence=true`, **no LLM call** |
| Model can't answer from the excerpts | it replies `INSUFFICIENT_EVIDENCE` → same friendly answer |
| Model cites a block that doesn't exist | marker removed before the user sees it |
| Provider blocked the reply (safety filter) | neutral "could not be generated" message |
| Missing/invalid key, unknown model or `RERANKER` | 503 "not configured" (details in logs only) |
| Rate limit / timeout / Qdrant down | 503 "temporarily unavailable" (one LLM retry first) |
| Instruction-like text in question or evidence | logged as `prompt_injection_suspected`; never obeyed as instructions, never blocks |
| Another user's `conversation_id` (same tenant) | 404 — conversations are private to their author |

## Settings

`LLM_PROVIDER` (gemini), `GEMINI_MODEL` (gemini-2.5-flash — confirm against Google's current model list), `LLM_TIMEOUT_S` (60), `LLM_MAX_OUTPUT_TOKENS` (1024), `RETRIEVAL_PREFETCH` (40), `RETRIEVAL_CANDIDATES` (20), `RERANK_TOP_N` (6), `RERANKER` (heuristic | none), `CONTEXT_MAX_TOKENS` (6000), `CONVERSATION_HISTORY_TURNS` (3).

Ollama is supported for generation as well: `LLM_PROVIDER=ollama`, `OLLAMA_MODEL=llama3.1:8b`.

## Known limits (next phases)

* Follow-ups use conversation history for the answer, but retrieval uses only the new question; pronoun-heavy follow-ups ("what about that one?") may retrieve poorly. Query rewriting belongs to the Phase 8 agent.
* `cited_fraction` is a citation-coverage signal, not a groundedness check; claim-level evidence validation is Phase 11. Evaluation of retrieval/answer quality (Recall@K, MRR, faithfulness) is Phase 12.
* Answers are returned whole (no token streaming yet).
* The heuristic reranker is not a neural cross-encoder; see `app/rag/reranker.py` for why and how to plug one in.
