# Agentic RAG — LangGraph agent (Phase 8)

`POST /query` runs this agent by default (`mode: "agent"`). It wraps the Phase 7 pipeline in a stateful workflow that rewrites follow-ups, splits multi-part questions, checks its evidence and retries weak searches. `mode: "fast"` runs the single-pass Phase 7 pipeline instead.

## Graph

```text
START
  └─ understand ──(route by intent; Phase 8: all -> qa)──► retrieve ◄──────────┐
                                                              ▼                 │
                                                           rerank               │
                                                              ▼                 │
                          not_found ◄── nothing in scope ── validate ── weak, retries left ─► refine
                              │                               │
                             END                   relevant (or out of retries)
                                                              ▼
                                                  context ─► generate ─► cite ─► END
```

| Node | What it does | LLM call? |
|---|---|---|
| understand | follow-up → standalone question; multi-part → ≤3 sub-questions; intent | only if there is history or the question looks multi-part |
| retrieve | one `search_contracts` tool call per query; repeats are skipped | no |
| rerank | rerank each query's hits against that query, merge round-robin | no |
| validate | nothing found → not_found; relevant → answer; weak → refine | no |
| refine | model proposes alternative (legal) wording; nothing new → stop retrying | yes |
| context | `get_sections` tool → small-to-big evidence blocks | no |
| generate | answer from evidence only (same prompt as Phase 7) | yes |
| cite | verify/renumber citations; `INSUFFICIENT_EVIDENCE` → not found | no |

"Relevant" = a top chunk names a clause the question (or a search query) names, or shares ≥20% of its content words.

## Code map

| Module | Responsibility |
|---|---|
| `app/agents/graph.py` | graph wiring, tools, `AgentRunner` (step limit, timeout) |
| `app/agents/state.py` | `AgentState` (tenant/role read-only; steps/flags/errors accumulate) |
| `app/agents/supervisor.py` | `understand` node, planning heuristic, `route` |
| `app/agents/retrieval_agent.py` | retrieve / rerank / validate / refine, `after_validate` edge |
| `app/agents/answering.py` | context / generate / cite / not_found |
| `app/agents/tools/registry.py` | tool registry: permission, tenant injection, budget |
| `app/agents/prompts.py` | planning prompts (`AGENT_PROMPT_VERSION`), strict JSON parsing |
| `app/agents/results.py`, `errors.py` | result/exception types, importable without LangGraph |

## Guardrails (enforced in code)

| Guardrail | Setting | Behaviour |
|---|---|---|
| Tenant isolation | — | `tenant_id`/`role` set by the API from the token; tools receive them from the registry; a tool call carrying `tenant_id`/`role` in its arguments is refused |
| Permission | — | each tool declares a `Permission`; checked against the caller's role |
| Retry limit | `AGENT_MAX_RETRIES` (2) | refine rounds; "nothing new to try" ends the loop at once |
| Tool budget | `AGENT_MAX_TOOL_CALLS` (12) | searches per question across retries; over budget → answer with what was found |
| Duplicate actions | — | an identical search is never run twice in one question |
| Step limit | derived from the retry limit | LangGraph `recursion_limit`; hitting it → safe "not found", logged as an error |
| Time limit | `AGENT_TIMEOUT_S` (90) | whole run; exceeded → 503 "temporarily unavailable" |
| Planning safety | — | planning replies are parsed strictly (types, lengths, allowed intents); anything malformed → original question |

## Response additions

```json
"mode": "agent",
"agent": {
  "intent": "compare",
  "standalone_question": "Compare the notice periods in the MSA and the SOW",
  "queries": ["MSA notice period", "SOW notice period"],
  "retries": 0,
  "tool_calls": 2
}
```

`steps` gains `understand`, `validate` and (when used) `refine`.

## Cost & latency

A standalone single-part question costs exactly what fast mode costs (one generation call). Planning adds one short call only for follow-ups and multi-part questions; each refine round adds one short call and one search. `usage` reports the answer-generation call only.

## Decisions

* **LangGraph without LangChain chat models.** Nodes call `app/llm` providers directly (one LLM layer; Gemini/Ollama switching stays in `.env`). Only `langgraph` is a dependency (it brings `langchain-core`).
* **The agent is loaded on first use**, not at API start-up: a missing agent dependency makes agent-mode questions return "not configured" instead of stopping the whole API.
* **Specialists come in Phase 10.** `route()` sends every intent (qa, compare, risk, summarize, extract, multi_document) through retrieval QA for now; comparison/risk/summary agents plug in there.
* **No checkpointing yet.** Each question is one graph run; conversation memory is the persisted message history.
